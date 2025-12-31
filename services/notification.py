"""
Notification Service - Telegram interactive bot.
Sends alerts and handles CV uploads.
"""
from typing import Optional, Callable
from pathlib import Path
import asyncio
from datetime import datetime, timezone

import bleach
from telegram import Update, BotCommand, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    filters,
    CallbackQueryHandler,
    ConversationHandler
)
from telegram.error import TelegramError, NetworkError
from telegram.request import HTTPXRequest

from core import setup_logger, settings
from services.matcher import matcher_service

from services.storage import storage_service

logger = setup_logger(__name__, "notification.log")

# Conversation States
MENU, EDIT_LOCS, EDIT_KEYWORDS, EDIT_THRESHOLD, EDIT_CATEGORIES, CONFIRM_KEYWORDS, EDIT_KEYWORD_MODE, CONFIRM_RESET = range(8)


class NotificationService:
    """
    Service for sending Telegram notifications and handling user interactions.
    
    Features:
    - Formatted job alerts
    - Unidirectional notifications
    - Interactive CV upload (PDF)
    - User commands (/stats, /mycv)
    """
    
    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log Errors caused by Updates."""
        error = context.error
        
        # Ignore harmless "Message is not modified" errors (user clicked button that doesn't change state)
        if isinstance(error, TelegramError) and "Message is not modified" in str(error):
            logger.debug(f"Ignoring harmless 'Message is not modified' error: {error}")
            return
        
        # Log real errors
        logger.error(f"Update {update} caused error {error}")
        if isinstance(error, NetworkError):
            logger.warning("Network error detected. Telegram bot will automatically attempt to reconnect.")

    def __init__(self):
        self.app: Optional[Application] = None
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.trigger_event: Optional[asyncio.Event] = None
        self.next_run_getter: Optional[Callable] = None
        self.status_getter: Optional[Callable] = None
        self.reset_trigger: Optional[Callable] = None
        self.stop_search_handler: Optional[Callable] = None
        self.last_summary_msg_id: Optional[int] = None
        self.last_total_offers: int = 0
        self.last_high_matches: int = 0
        self.search_manually_stopped: bool = False
    
    def _get_menu_keyboard(self, sys_settings) -> InlineKeyboardMarkup:
        """Build the interactive configuration menu keyboard."""
        rem_text = "✅ YES" if sys_settings.include_remote else "❌ NO"
        locs_text = sys_settings.locations if sys_settings.locations else "All"
        
        # Get keyword match mode
        keyword_mode = getattr(sys_settings, 'keyword_match_mode', 'relaxed')
        mode_emoji = {
            'relaxed': '🟢',    # Green - most permissive
            'moderate': '🟡',   # Yellow - balanced
            'strict': '🔴'      # Red - strict
        }
        mode_label = {
            'relaxed': 'Relaxed (1+ keyword)',
            'moderate': 'Moderate (40%)',
            'strict': 'Strict (80%)'
        }
        mode_display = f"{mode_emoji.get(keyword_mode, '🟢')} {mode_label.get(keyword_mode, 'Relaxed')}"
        
        keyboard = [
            [
                InlineKeyboardButton("🚀 SEARCH NOW", callback_data="trigger_search"),
                InlineKeyboardButton("🛑 STOP SEARCH", callback_data="stop_search"),
            ],
            [
                InlineKeyboardButton("📊 Statistics", callback_data="show_stats"),
                InlineKeyboardButton("📂 My CV", callback_data="show_cv"),
            ],
            [
                InlineKeyboardButton("🌐 Sources", callback_data="show_sources"),
                InlineKeyboardButton(f"🌍 Cities: {locs_text}", callback_data="edit_locs"),
            ],
            [
                InlineKeyboardButton(f"🏠 Remote: {rem_text}", callback_data="toggle_remote"),
                InlineKeyboardButton(f"🎯 Threshold: {sys_settings.match_threshold}%", callback_data="edit_thresh"),
            ],
            [
                InlineKeyboardButton(f"🔍 Keywords: {sys_settings.search_keywords}", callback_data="edit_keys"),
                InlineKeyboardButton(f"📁 Category IDs: {sys_settings.category_ids}", callback_data="edit_cats"),
            ],
            [
                InlineKeyboardButton(f"⚙️ Match Mode: {mode_display}", callback_data="edit_keyword_mode"),
            ],
            [
                InlineKeyboardButton("❓ Help & Guides", callback_data="show_help"),
            ],

        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def initialize(self) -> None:
        """Initialize Telegram Application and register commands."""
        try:
            # Configure custom timeouts for unstable network connections
            request = HTTPXRequest(
                connect_timeout=30.0,
                read_timeout=30.0,
                write_timeout=30.0,
                pool_timeout=10.0,
            )
            
            builder = Application.builder().token(self.bot_token).request(request)
            self.app = builder.build()
            
            # Define Conversation Handler for the interactive menu
            conv_handler = ConversationHandler(
                entry_points=[
                    CommandHandler("start", self._start_command),
                    CallbackQueryHandler(self._button_handler),
                ],
                states={
                    MENU: [
                        CallbackQueryHandler(self._button_handler),
                    ],
                    EDIT_LOCS: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_locs_input),
                        CallbackQueryHandler(self._button_handler),
                    ],
                    EDIT_KEYWORDS: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_keys_input),
                        CallbackQueryHandler(self._button_handler),
                    ],
                    EDIT_KEYWORD_MODE: [
                        CallbackQueryHandler(self._button_handler),
                    ],
                    EDIT_CATEGORIES: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_cats_input),
                        CallbackQueryHandler(self._button_handler),
                    ],
                    EDIT_THRESHOLD: [
                        CallbackQueryHandler(self._button_handler),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_thresh_input),
                    ],
                    CONFIRM_KEYWORDS: [
                        CallbackQueryHandler(self._handle_confirm_keywords_callback),
                    ],
                },
                fallbacks=[CommandHandler("cancel", self._cancel_command)],
                allow_reentry=True,
                per_user=True,
                per_chat=True,
            )
            
            self.app.add_handler(conv_handler)
            
            # Global error handler
            self.app.add_error_handler(self._error_handler)
            
            # Keep standalone handlers for quick access
            self.app.add_handler(CommandHandler("help", self.help_command))
            self.app.add_handler(CommandHandler("stats", self._stats_command))
            self.app.add_handler(CommandHandler("mycv", self._mycv_command))
            self.app.add_handler(CommandHandler("reset", self._reset_command))
            self.app.add_handler(MessageHandler(filters.Document.PDF, self._handle_cv_upload))
            
            await self.app.initialize()
            await self.app.start()
            
            # Register commands with Telegram (shows them in the menu)
            commands = [
                BotCommand("start", "Control Panel"),
                BotCommand("help", "How AI Works & Guides"),
                BotCommand("stats", "Work statistics"),
                BotCommand("mycv", "View your CV settings"),
                BotCommand("reset", "Force full re-analysis"),
            ]
            await self.app.bot.set_my_commands(commands)
            
            # Note: We don't start polling here to avoid blocking. 
            # It will be handled by the main loop or a separate task.
            
            logger.info("Notification service (Telegram Bot) initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}", exc_info=True)
            raise

    async def start_polling(self) -> None:
        """Start receiving updates (polling)."""
        if self.app:
            logger.info("Starting Telegram polling...")
            await self.app.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                bootstrap_retries=-1, # Infinite retries during startup
                read_timeout=60.0       # Increased timeout for slower connections
            )

    async def stop(self) -> None:
        """Stop the bot."""
        if self.app:
            if self.app.updater and self.app.updater.running:
                await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Notification service stopped")

    def set_next_run_getter(self, getter_func: Callable) -> None:
        """Set a function that returns the datetime of the next run."""
        self.next_run_getter = getter_func

    def set_status_getter(self, getter_func: Callable) -> None:
        """Set a function that returns the current processing status."""
        self.status_getter = getter_func

    def set_reset_trigger(self, trigger_func: Callable) -> None:
        """Set a function to trigger a full re-scan (reset + fetch)."""
        self.reset_trigger = trigger_func

    def _get_countdown_text(self) -> str:
        """Calculate and format time until next run."""
        # Check if currently running
        if self.status_getter and self.status_getter():
            return "🔄 <b>Scanning for offers now...</b>"
            
        if not self.next_run_getter:
            return ""
        
        # Check if search was manually stopped
        if self.search_manually_stopped:
            return "🛑 <b>Search stopped</b> <i>(click Search Now to resume)</i>"
            
        # Check if search is currently running
        if self.status_getter and self.status_getter():
            return "🔄 <b>Search in progress...</b>"
        
        next_run = self.next_run_getter()
        if not next_run:
            return "⏳ <i>Initializing scheduler...</i>"
        
        # Ensure both datetimes are timezone-aware for comparison
        now = datetime.now(timezone.utc)
        
        # If next_run is naive, make it aware
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
            
        if next_run <= now:
            return "🔄 <b>Starting scan...</b>"
            
        diff = next_run - now
        minutes = int(diff.total_seconds() // 60)
        seconds = int(diff.total_seconds() % 60)
        
        return f"⏱ <b>Next auto-scan in: {minutes:02d}:{seconds:02d}</b>"

    async def send_scan_summary(self, total_offers: int, high_matches: int, last_scan_time: Optional[datetime] = None) -> None:
        """Send or update a summary message after a scan cycle."""
        if not self.app:
            return
            
        self.last_total_offers = total_offers
        self.last_high_matches = high_matches
        now_str = datetime.now().strftime("%H:%M:%S")
        prev_str = last_scan_time.strftime("%H:%M:%S") if last_scan_time else "First run"
        
        header = "🔄 <b>Scan in progress...</b>" if self.status_getter and self.status_getter() else "✅ <b>Scan Complete!</b>"
        
        msg = (
            f"{header}\n\n"
            f"📥 <b>Offers downloaded:</b> {total_offers}\n"
            f"🎯 <b>High quality matches:</b> {high_matches}\n\n"
            f"🕒 <b>Previous scan:</b> {prev_str}\n"
            f"⌛ <b>Current time:</b> {now_str}\n\n"
            "<i>I will notify you immediately if I find anything new matching your criteria.</i>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 REFRESH TIME", callback_data="refresh_summary")],
            [InlineKeyboardButton("⚙️ Open Filters", callback_data="back_to_menu")]
        ])
        
        try:
            if self.last_summary_msg_id:
                try:
                    await self.app.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self.last_summary_msg_id,
                        text=msg,
                        reply_markup=markup,
                        parse_mode="HTML"
                    )
                    logger.info(f"Updated scan summary message: {self.last_summary_msg_id}")
                    return
                except TelegramError as te:
                    # If message is too old to edit or deleted, we'll send a new one
                    # This is normal behavior, not an error
                    logger.debug(f"Could not edit scan summary (might be deleted or too old), sending new message: {te}")
            
            # Send new message if no previous ID or editing failed
            sent_msg = await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=msg,
                reply_markup=markup,
                parse_mode="HTML"
            )
            self.last_summary_msg_id = sent_msg.message_id
            logger.info(f"Sent new scan summary message: {self.last_summary_msg_id}")
            
        except Exception as e:
            logger.error(f"Error sending/editing scan summary: {e}")

    async def _render_menu(self, update: Update, sys_settings=None, edit: bool = False) -> None:
        """Render the main configuration menu with logo."""
        if not sys_settings:
            sys_settings = await storage_service.get_system_settings()
            
        # Get keyword match mode display
        keyword_mode = getattr(sys_settings, 'keyword_match_mode', 'relaxed')
        mode_names = {
            'relaxed': '🟢 Relaxed',
            'moderate': '🟡 Moderate',
            'strict': '🔴 Strict'
        }
        mode_display = mode_names.get(keyword_mode, '🟢 Relaxed')
        
        countdown = self._get_countdown_text()
        text = (
            f"⚙️ <b>JobSniper - Control Panel</b>\n"
            f"{countdown}\n\n"
            f"🌍 <b>Cities:</b> {sys_settings.locations or 'All'}\n"
            f"🏠 <b>Remote:</b> {'✅ YES' if sys_settings.include_remote else '❌ NO'}\n"
            f"🎯 <b>Threshold:</b> {sys_settings.match_threshold}%\n"
            f"🔍 <b>Keywords:</b> {sys_settings.search_keywords}\n"
            f"⚙️ <b>Match Mode:</b> {mode_display}\n"
            f"📁 <b>Categories:</b> {sys_settings.category_ids}\n\n"
            "<i>Select a button below to change settings or start search.</i>"
        )
        
        reply_markup = self._get_menu_keyboard(sys_settings)
        logo_path = Path("images/logo.png")
        
        if edit and update.callback_query:
            try:
                # If current message is a photo, edit caption
                if update.callback_query.message.photo:
                    await update.callback_query.edit_message_caption(
                        caption=text, 
                        reply_markup=reply_markup, 
                        parse_mode="HTML"
                    )
                else:
                    # Current message is text, send new photo message and delete old one
                    if logo_path.exists():
                        with open(logo_path, "rb") as photo:
                            await self.app.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=photo,
                                caption=text,
                                reply_markup=reply_markup,
                                parse_mode="HTML"
                            )
                        await update.callback_query.message.delete()
                    else:
                        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error editing menu with photo: {e}")
                # Fallback to text edit
                try:
                    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
                except:
                    pass
        else:
            # Initial /start or new message
            if logo_path.exists():
                with open(logo_path, "rb") as photo:
                    await self.app.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=photo,
                        caption=text,
                        reply_markup=reply_markup,
                        parse_mode="HTML"
                    )
            else:
                await update.effective_message.reply_html(text, reply_markup=reply_markup)

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /start command - Show the main menu."""
        await self._render_menu(update)
        return MENU

    async def _render_cv_menu(self, update: Update, edit: bool = False) -> None:
        """Render the CV management sub-menu."""
        cv_text = matcher_service.cv_text
        status = "✅ <b>Loaded</b>" if cv_text else "❌ <b>Missing</b>"
        count = len(cv_text) if cv_text else 0
        
        text = (
            "📁 <b>CV Management</b>\n\n"
            f"Status: {status}\n"
            f"Text length: {count} characters\n\n"
            "📖 <b>Instructions:</b>\n"
            "To upload a new version or replace the current one, simply <b>send me a PDF file</b> any time.\n\n"
            "<i>Select an option below:</i>"
        )
        
        keyboard = []
        if cv_text:
            keyboard.append([InlineKeyboardButton("👁️ View text preview", callback_data="view_cv_text")])
            keyboard.append([InlineKeyboardButton("❌ Delete my CV", callback_data="delete_cv")])
            
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if edit and update.callback_query:
            try:
                # If current message is a photo, edit caption
                if update.callback_query.message.photo:
                    await update.callback_query.edit_message_caption(
                        caption=text, 
                        reply_markup=reply_markup, 
                        parse_mode="HTML"
                    )
                else:
                    # Current message is text
                    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error editing CV menu: {e}")
                try:
                    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
                except:
                    pass
        else:
            msg = update.effective_message
            await msg.reply_html(text, reply_markup=reply_markup)
    
    async def _render_sources_menu(self, update: Update, edit: bool = False) -> None:
        """Render the job sources selection menu."""
        sys_settings = await storage_service.get_system_settings()
        enabled = [s.strip() for s in sys_settings.enabled_sources.split(",") if s.strip()]
        
        # Source definitions
        sources = {
            "jjit": "🇵🇱 Just Join IT",
            "remoteok": "🌎 RemoteOK",
            "remotive": "🌍 Remotive",
            "weworkremotely": "💼 We Work Remotely",
            "arbeitnow": "🇪🇺 Arbeitnow",
        }
        
        text = (
            "🌐 <b>Job Board Sources</b>\n\n"
            "Select which job boards to search:\n\n"
        )
        
        keyboard = []
        for source_id, source_name in sources.items():
            is_enabled = source_id in enabled
            status = "✅" if is_enabled else "❌"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {source_name}",
                    callback_data=f"toggle_source_{source_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if edit and update.callback_query:
            try:
                if update.callback_query.message.photo:
                    await update.callback_query.edit_message_caption(
                        caption=text,
                        reply_markup=reply_markup,
                        parse_mode="HTML"
                    )
                else:
                    await update.callback_query.edit_message_text(
                        text,
                        reply_markup=reply_markup,
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.error(f"Error editing sources menu: {e}")
                try:
                    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
                except:
                    pass
        else:
            msg = update.effective_message
            await msg.reply_html(text, reply_markup=reply_markup)
    
    async def _toggle_source(self, source_id: str) -> None:
        """Toggle a job source on/off."""
        logger.info(f"Toggling source: {source_id}")
        sys_settings = await storage_service.get_system_settings()
        enabled = [s.strip() for s in sys_settings.enabled_sources.split(",") if s.strip()]
        
        if source_id in enabled:
            enabled.remove(source_id)
            logger.info(f"Disabled source: {source_id}")
        else:
            enabled.append(source_id)
            logger.info(f"Enabled source: {source_id}")
        
        new_value = ",".join(enabled) if enabled else "jjit"  # Default to jjit if all disabled
        await storage_service.update_system_settings(enabled_sources=new_value)

    async def _button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle inline button clicks."""
        query = update.callback_query
        data = query.data
        logger.info(f"Button clicked: {data}")
        
        # Only answer automatically if no custom alert text is needed later in this handler
        # These paths provide their own answers with specific text or alerts
        manual_answer_paths = [
            "trigger_search", "stop_search", "refresh_summary", "clear_locs", 
            "cv_help", "delete_cv", "apply_suggested", "edit_suggested"
        ]
        if data not in manual_answer_paths:
            await query.answer()
        
        sys_settings = await storage_service.get_system_settings()
        
        if data == "toggle_remote":
            new_val = not sys_settings.include_remote
            await storage_service.update_system_settings(include_remote=new_val)
            await self._render_menu(update, edit=True)
            await self._render_menu(update, edit=True)
            return MENU

        elif data == "show_help":
            await self.help_command(update, context)
            return MENU
            
        elif data == "edit_locs":

            logger.info("User requested city edit")
            current = sys_settings.locations or "<i>Searching everywhere</i>"
            text = (
                "🌍 <b>Edit Cities</b>\n\n"
                f"<b>Current:</b> <code>{current}</code>\n\n"
                "Enter city names separated by commas (e.g., <code>London, Warsaw, Berlin</code>).\n"
                "Click <b>🗑️ Clear Cities</b> or type <code>clear</code> to search everywhere.\n"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Clear Cities", callback_data="clear_locs")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
            ])
            
            logger.debug("Editing message for cities prompt")
            logger.debug("Attempting to update message content for city edit")
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption=text, reply_markup=markup, parse_mode="HTML")
                else:
                    await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
                logger.info("City edit message prompt sent successfully")
            except Exception as e:
                logger.error(f"Failed to edit message for city prompt: {e}", exc_info=True)
                await query.answer("❌ Error opening editor.", show_alert=True)
            return EDIT_LOCS
            
        elif data == "clear_locs":
            logger.info("User requested to clear cities via button")
            await storage_service.update_system_settings(locations="")
            
            # Reset trigger if needed
            if self.reset_trigger:
                self.reset_trigger()
            elif self.trigger_event:
                self.trigger_event.set()
                
            await query.answer("✅ Cities cleared!")
            
            # Refresh the edit view to show "Searching everywhere"
            current = "<i>Searching everywhere</i>"
            text = (
                "🌍 <b>Edit Cities</b>\n\n"
                f"<b>Current:</b> <code>{current}</code>\n\n"
                "Enter city names separated by commas (e.g., <code>London, Warsaw, Berlin</code>).\n"
                "Click <b>🗑️ Clear</b> or type <code>clear</code> to search everywhere.\n"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Clear", callback_data="clear_locs")],
                [InlineKeyboardButton("⬅️ Back to menu", callback_data="back_to_menu")]
            ])
            
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=markup, parse_mode="HTML")
            else:
                await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
            return EDIT_LOCS

        elif data == "edit_keys":
            current = sys_settings.search_keywords or "<i>None</i>"
            text = (
                "🔍 <b>Edit Keywords</b>\n\n"
                f"<b>Current:</b> <code>{current}</code>\n\n"
                "Keywords are searched in:\n"
                "• <b>Job title</b>\n"
                "• <b>City</b>\n"
                "• <b>Required skills</b>\n\n"
                "You can provide multiple phrases separated by commas (e.g., <code>Python, Django, Senior</code>) to match any offers containing <b>all</b> of these phrases.\n"
            )
            
            # Add Clear button if keywords exist
            buttons = []
            if sys_settings.search_keywords:
                buttons.append([InlineKeyboardButton("🗑️ Clear Keywords", callback_data="clear_keywords")])
                buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")])
            else:
                buttons.append([InlineKeyboardButton("⬅️ Back to menu", callback_data="back_to_menu")])
            
            markup = InlineKeyboardMarkup(buttons)
            
            logger.info("User requested keyword edit")
            logger.debug("Attempting to update message content for keyword edit")
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption=text, reply_markup=markup, parse_mode="HTML")
                else:
                    await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
                logger.info("Keyword edit message prompt sent successfully")
            except Exception as e:
                logger.error(f"Failed to edit message for keyword prompt: {e}", exc_info=True)
                await query.answer("❌ Error opening editor.", show_alert=True)
            return EDIT_KEYWORDS

        elif data == "edit_cats":
            current = sys_settings.category_ids or "<i>None</i>"
            text = (
                "📁 <b>Just Join IT Categories</b>\n\n"
                f"<b>Current IDs:</b> <code>{current}</code>\n\n"
                "Available IDs:\n"
                "1: Javascript, 2: HTML, 3: PHP, 4: Ruby, 5: Python, 6: Java, 7: .Net, 8: Scala, 9: C, 10: Mobile, 11: Testing, 12: DevOps, 13: Admin, 14: UX, 15: PM, 16: Game, 17: Analytics, 18: Security, 19: Data, 20: Go, 21: SAP, 22: Support, 23: Other, 24: Architecture, 25: ERP, 26: AI\n\n"
                "Enter the ID of the selected category (e.g., <code>5</code> or <code>5, 12</code>).\n"
            )
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to menu", callback_data="back_to_menu")]])
            
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=markup, parse_mode="HTML")
            else:
                await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
            return EDIT_CATEGORIES

        elif data == "edit_keyword_mode":
            # Show keyword match mode selector
            current_mode = getattr(sys_settings, 'keyword_match_mode', 'relaxed')
            text = (
                "⚙️ <b>Keyword Matching Mode</b>\n\n"
                "Choose how strictly keywords should match job offers:\n\n"
                "🟢 <b>Relaxed</b> - At least <b>1 keyword</b> must match\n"
                "   <i>Most results, good for exploration</i>\n\n"
                "🟡 <b>Moderate</b> - At least <b>40%</b> of keywords must match\n"
                "   <i>Balanced, recommended for most users</i>\n\n"
                "🔴 <b>Strict</b> - At least <b>80%</b> of keywords must match\n"
                "   <i>Fewer results, very specific matching</i>\n\n"
                f"Current mode: <b>{current_mode.capitalize()}</b>\n\n"
                "Select new mode:"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🟢 Relaxed (1+ keyword)", callback_data="set_mode_relaxed")],
                [InlineKeyboardButton("🟡 Moderate (40%)", callback_data="set_mode_moderate")],
                [InlineKeyboardButton("🔴 Strict (80%)", callback_data="set_mode_strict")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
            ])
            
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=markup, parse_mode="HTML")
            else:
                await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
            return EDIT_KEYWORD_MODE
        
        elif data.startswith("set_mode_"):
            # Handle mode selection
            mode = data.replace("set_mode_", "")
            await storage_service.update_system_settings(keyword_match_mode=mode)
            logger.info(f"Keyword match mode changed to: {mode}")
            await self._render_menu(update, edit=True)
            return MENU
        
        elif data == "clear_keywords":
            # Clear all keywords
            try:
                await storage_service.update_system_settings(search_keywords="")
                
                # Critical: trigger re-scan/reset so changes take effect immediately
                if self.reset_trigger:
                    self.reset_trigger()
                elif self.trigger_event:
                    self.trigger_event.set()

                await query.answer("✅ Keywords cleared!")
                logger.info("Keywords cleared by user")
                
                # Stay in keyword edit view
                text = (
                    "🔍 <b>Edit Keywords</b>\n\n"
                    "<b>Current:</b> <i>None</i>\n\n"
                    "Keywords are searched in:\n"
                    "• <b>Job title</b>\n"
                    "• <b>City</b>\n"
                    "• <b>Required skills</b>\n\n"
                    "You can provide multiple phrases separated by commas (e.g., <code>Python, Django, Senior</code>) to match any offers containing <b>all</b> of these phrases.\n"
                )
                markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]])
                
                if query.message.photo:
                    await query.edit_message_caption(caption=text, reply_markup=markup, parse_mode="HTML")
                else:
                    await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
                return EDIT_KEYWORDS
            except Exception as e:
                logger.error(f"Failed to clear keywords: {e}")
                await query.answer("❌ Failed to clear keywords.", show_alert=True)
                return MENU

        elif data == "edit_thresh":
            text = (
                "🎯 <b>AI Match Threshold</b>\n\n"
                "This threshold determines how much an offer must match your CV (0-100%) for you to receive a notification.\n"
                "• <b>80%+</b>: Only highly matched offers (high quality, less noise).\n"
                "• <b>50%+</b>: Broader range, will also show offers touching on your skills.\n\n"
                "Select a value:"
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("20%", callback_data="set_thresh_20"),
                    InlineKeyboardButton("30%", callback_data="set_thresh_30"),
                    InlineKeyboardButton("40%", callback_data="set_thresh_40"),
                    InlineKeyboardButton("50%", callback_data="set_thresh_50"),
                ],
                [
                    InlineKeyboardButton("60%", callback_data="set_thresh_60"),
                    InlineKeyboardButton("70%", callback_data="set_thresh_70"),
                    InlineKeyboardButton("80%", callback_data="set_thresh_80"),
                    InlineKeyboardButton("90%", callback_data="set_thresh_90"),
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
            ])
            
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=markup, parse_mode="HTML")
            else:
                await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
            return EDIT_THRESHOLD

        elif data.startswith("set_thresh_"):
            try:
                value = int(data.replace("set_thresh_", ""))
                await storage_service.update_system_settings(match_threshold=value)
                await query.answer(f"✅ Threshold set to {value}%", show_alert=True)
                if self.reset_trigger:
                    self.reset_trigger()
                await self._render_menu(update, edit=True)
                return MENU
            except Exception as e:
                logger.error(f"Error setting threshold: {e}")
                await query.answer("❌ Error setting threshold", show_alert=True)
                return MENU
            
        elif data == "trigger_search":
            # 🛡️ Double-click protection
            if self.status_getter and self.status_getter():
                logger.info("Ignored trigger_search: scan in progress")
                await query.answer("⚠️ Scan is already in progress! Please wait for results to appear in the chat.", show_alert=True)
                return MENU
                
            if not matcher_service.cv_text:
                await query.answer() # Stop spinner
                await update.effective_message.reply_html(
                    "⚠️ <b>CV Required!</b>\n\n"
                    "I cannot analyze job offers without your CV.\n\n"
                    "👉 <b>To upload:</b> Simply send me your CV in <b>PDF format</b> right here in this chat.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to menu", callback_data="back_to_menu")]])
                )
                return MENU
            
            # Clear the manually stopped flag BEFORE countdown
            self.search_manually_stopped = False
                
            # Countdown animation
            await query.answer() # Stop spinner
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Back to Set Filters", callback_data="back_to_menu")]])
            msg = await update.effective_message.reply_html("⏳ <b>Preparing search in 3...</b>")
            await asyncio.sleep(1)
            await msg.edit_text("⏳ <b>Preparing search in 2...</b>", parse_mode="HTML")
            await asyncio.sleep(1)
            await msg.edit_text("⏳ <b>Preparing search in 1...</b>", parse_mode="HTML")
            await asyncio.sleep(0.5)
            
            countdown = self._get_countdown_text()
            await msg.edit_text(f"🚀 <b>Starting search now...</b>\n{countdown}", reply_markup=markup, parse_mode="HTML")
            
            if self.trigger_event:
                logger.info("User triggered manual search via button with countdown")
                self.trigger_event.set()
            else:
                logger.warning("trigger_event not set in NotificationService")
            return MENU
        
        elif data == "stop_search":
            # Set visual flag immediately
            self.search_manually_stopped = True
            
            if self.stop_search_handler:
                try:
                    # This handler in main.py will cancel task AND disable auto-scan
                    stopped = await self.stop_search_handler()
                    if stopped:
                        await query.answer("✅ Search stopped!", show_alert=True)
                        logger.info("User stopped search via button (active search or auto-scan disabled)")
                    else:
                        await query.answer()
                except Exception as e:
                    logger.error(f"Error stopping search: {e}", exc_info=True)
                    await query.answer("❌ Failed to stop search. Please try again.", show_alert=True)
            else:
                await query.answer()
                
            # Refresh menu regardless to show "Search stopped" status
            await asyncio.sleep(0.3)
            await self._render_menu(update, edit=True)
            return MENU
        
        elif data == "apply_suggested":
            # Route to confirm keywords handler
            return await self._handle_confirm_keywords_callback(update, context)
            
        elif data == "edit_suggested":
            # Route to confirm keywords handler
            return await self._handle_confirm_keywords_callback(update, context)
            
        elif data == "show_stats":
            await self._stats_command(update, context)
            return MENU
            
        elif data == "show_cv":
            await self._render_cv_menu(update, edit=True)
            return MENU
        
        elif data == "show_sources":
            await self._render_sources_menu(update, edit=True)
            return MENU
        
        elif data.startswith("toggle_source_"):
            source_id = data.replace("toggle_source_", "")
            await self._toggle_source(source_id)
            await self._render_sources_menu(update, edit=True)
            return MENU
            
        elif data == "view_cv_text":
            await self._handle_view_cv_text(update, context)
            return MENU

        elif data == "cv_help":
            await query.answer("Send a PDF file with your CV to upload it.", show_alert=True)
            return MENU
            
        elif data == "delete_cv":
            success = await matcher_service.clear_cv()
            if success:
                await query.answer("✅ CV has been deleted.")
                await self._render_cv_menu(update, edit=True)
            else:
                await query.answer("❌ Error deleting CV.", show_alert=True)
            return MENU
            
        elif data == "refresh_summary":
            # Just update the existing summary message with current time/stats
            try:
                stats = await storage_service.get_statistics()
                # We need to find the last scan status to keep 'high_matches' accurate for that cycle
                # However, the user asked to 'only refresh time'. 
                # To be accurate, we'll re-run send_scan_summary which fetches latest stats.
                # If a cycle is NOT running, match_stats from main.py isn't easily accessible here
                # so we'll just use the cumulative stats from the DB for now or handle it gracefully.
                
                # For simplicity and to satisfy "only refresh time", we'll just call it again.
                # We'll use 0 for high_matches if we don't have the context, but better to keep it.
                # Actually, storage_service.get_statistics doesn't have "high_matches for LAST cycle".
                # Let's just update the message text manually or pass data.
                
                await self.send_scan_summary(
                    total_offers=self.last_total_offers,
                    high_matches=self.last_high_matches,
                    last_scan_time=stats['last_scan']
                )
                await query.answer("Time updated.")
            except Exception as e:
                logger.error(f"Error refreshing summary: {e}")
            return MENU
        elif data == "do_full_reset":
            # Perform the actual reset
            try:
                await query.answer("🧹 Resetting...")
                count = await storage_service.reset_analysis_status()
                
                # Send the specific confirmation message requested by user
                text = (
                    f"✅ <b>Reset complete for {count} offers!</b>\n"
                    f"All offers are now treated as new.\n\n"
                    f"🛑 <b>Current scan stopped.</b>\n"
                    f"Press 🚀 <b>SEARCH NOW</b> to start fresh analysis."
                )
                
                # We can't edit to this message because it's a completely different format (usually text only)
                # But let's try to edit if possible, or send new.
                try:
                    await query.edit_message_text(
                        text, 
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 SEARCH NOW", callback_data="trigger_search")]])
                    )
                except Exception:
                    await update.effective_message.reply_html(
                        text,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 SEARCH NOW", callback_data="trigger_search")]])
                    )

                # Trigger immediate processing/stop
                if self.reset_trigger:
                    self.reset_trigger()
                elif self.trigger_event:
                    self.trigger_event.set()
                
                logger.info(f"Full reset performed by user for {count} offers")
                return MENU
            except Exception as e:
                logger.error(f"Failed to perform full reset: {e}", exc_info=True)
                await query.answer("❌ Reset failed.", show_alert=True)
                return MENU

        elif data == "back_to_menu":
            await self._render_menu(update, edit=True)
            return MENU
            
        return MENU

    async def _input_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle text input for settings update."""
        text = update.effective_message.text
        state = context.user_data.get("state") # Manual state management if needed, but ConversationHandler handles it
        
        # Determine which attribute to update based on current state
        # In ConversationHandler, we know the state from the entry point
        # But we need to check which state we are in.
        
        # PTB ConversationHandler passes the state to the current handler
        # Let's check current state from context or define separate handlers.
        # For simplicity, I'll use separate handlers or check current state.
        
        return MENU # Placeholder

    async def _cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel editing and return to menu."""
        await update.effective_message.reply_text("❌ Change cancelled.")
        await self._render_menu(update)
        return MENU

    async def _handle_locs_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raw_input = update.effective_message.text or ""
        logger.info(f"Received city input: '{raw_input}'")
        
        # Sanitize input
        clean_input = bleach.clean(raw_input, strip=True)
        
        # Validate length
        if len(clean_input) > 500:
            await update.effective_message.reply_text(
                "❌ Input too long. Maximum 500 characters allowed."
            )
            return EDIT_LOCS
        
        # Handle 'clear' command
        if clean_input.lower() == "clear":
            logger.info("Clearing city filters")
            clean_input = ""
        
        # Validate cities if not empty
        if clean_input:
            logger.info(f"Starting city validation for: {clean_input}")
            cities = [c.strip() for c in clean_input.split(',') if c.strip()]
            invalid_cities = []
            valid_cities = []
            
            # Static list of popular IT cities (case-insensitive)
            POPULAR_CITIES = {
                # Poland
                'warsaw', 'warszawa', 'krakow', 'kraków', 'cracow', 'wroclaw', 'wrocław', 
                'poznan', 'poznań', 'gdansk', 'gdańsk', 'gdynia', 'sopot', 'tricity',
                'lodz', 'łódź', 'katowice', 'lublin', 'bialystok', 'białystok',
                'szczecin', 'bydgoszcz', 'rzeszow', 'rzeszów', 'gliwice', 'olsztyn',
                
                # Europe - Major Tech Hubs
                'london', 'berlin', 'amsterdam', 'paris', 'munich', 'münchen',
                'dublin', 'barcelona', 'madrid', 'lisbon', 'lisboa', 'prague', 'praha',
                'vienna', 'wien', 'zurich', 'zürich', 'stockholm', 'copenhagen', 'københavn',
                'oslo', 'helsinki', 'budapest', 'brussels', 'bruxelles', 'rome', 'roma',
                'milan', 'milano', 'athens', 'athina', 'bucharest', 'bucuresti',
                
                # USA & Canada
                'new york', 'nyc', 'san francisco', 'sf', 'seattle', 'austin', 'boston',
                'los angeles', 'la', 'chicago', 'denver', 'portland', 'miami', 
                'atlanta', 'dallas', 'washington', 'dc', 'toronto', 'vancouver', 
                'montreal', 'montréal',
                
                # Asia-Pacific
                'singapore', 'tokyo', 'bangalore', 'bengaluru', 'sydney', 'melbourne',
                'hong kong', 'shanghai', 'beijing', 'seoul', 'taipei', 'tel aviv',
                'dubai', 'mumbai', 'hyderabad', 'pune',
                
                # Remote/Global
                'remote', 'worldwide', 'global', 'anywhere', 'nomad'
            }
            
            # Validate user input
            for city in cities:
                city_lower = city.lower().strip()
                
                # Check for exact match
                if city_lower in POPULAR_CITIES:
                    valid_cities.append(city)
                    logger.debug(f"City '{city}' is valid")
                else:
                    # Try to find similar cities with 70% similarity threshold
                    from difflib import SequenceMatcher
                    
                    def similarity(a, b):
                        return SequenceMatcher(None, a, b).ratio()
                    
                    # Find cities with at least 70% similarity
                    similar_cities = []
                    for known_city in POPULAR_CITIES:
                        sim_score = similarity(city_lower, known_city)
                        if sim_score >= 0.70:
                            similar_cities.append((known_city, sim_score))
                    
                    if similar_cities:
                        # Use the most similar match
                        best_match = max(similar_cities, key=lambda x: x[1])[0]
                        
                        # Capitalize properly
                        if best_match in ['warsaw', 'warszawa']:
                            corrected = 'Warsaw'
                        elif best_match in ['krakow', 'kraków', 'cracow']:
                            corrected = 'Krakow'
                        elif best_match in ['wroclaw', 'wrocław']:
                            corrected = 'Wroclaw'
                        elif best_match in ['poznan', 'poznań']:
                            corrected = 'Poznan'
                        elif best_match in ['gdansk', 'gdańsk']:
                            corrected = 'Gdansk'
                        elif best_match in ['lodz', 'łódź']:
                            corrected = 'Lodz'
                        elif best_match == 'new york' or best_match == 'nyc':
                            corrected = 'New York'
                        elif best_match == 'san francisco' or best_match == 'sf':
                            corrected = 'San Francisco'
                        elif best_match == 'los angeles' or best_match == 'la':
                            corrected = 'Los Angeles'
                        elif best_match == 'tel aviv':
                            corrected = 'Tel Aviv'
                        elif best_match == 'hong kong':
                            corrected = 'Hong Kong'
                        else:
                            corrected = best_match.title()
                        
                        valid_cities.append(corrected)
                        if corrected.lower() != city_lower:
                            sim_percent = int(max(similar_cities, key=lambda x: x[1])[1] * 100)
                            logger.info(f"Auto-corrected '{city}' to '{corrected}' (similarity: {sim_percent}%)")
                    else:
                        invalid_cities.append(city)
                        logger.warning(f"City '{city}' not found (no match with 70%+ similarity)")
            
            if invalid_cities:
                # Show list of popular cities
                top_cities = [
                    'Warsaw', 'Krakow', 'Wroclaw', 'Poznan', 'Gdansk', 'Katowice',
                    'London', 'Berlin', 'Amsterdam', 'Paris', 'Munich', 'Dublin',
                    'New York', 'San Francisco', 'Seattle', 'Austin', 'Boston',
                    'Singapore', 'Tokyo', 'Tel Aviv', 'Remote'
                ]
                logger.info(f"Rejecting invalid cities: {invalid_cities}")
                await update.effective_message.reply_text(
                    f"⚠️ <b>Invalid cities:</b> <code>{', '.join(invalid_cities)}</code>\n\n"
                    f"These cities were not found in our database.\n\n"
                    f"<b>Popular IT cities:</b>\n"
                    f"🇵🇱 <code>Warsaw, Krakow, Wroclaw, Poznan, Gdansk, Katowice</code>\n"
                    f"🇪🇺 <code>London, Berlin, Amsterdam, Paris, Munich, Dublin</code>\n"
                    f"🇺🇸 <code>New York, San Francisco, Seattle, Austin, Boston</code>\n"
                    f"🌏 <code>Singapore, Tokyo, Tel Aviv, Remote</code>",
                    parse_mode="HTML"
                )
                return EDIT_LOCS
            
            # Update clean_input with validated/corrected cities
            if valid_cities != cities:
                logger.info(f"Cities corrected: {cities} -> {valid_cities}")
                await update.effective_message.reply_text(
                    f"✏️ Auto-corrected: {', '.join(valid_cities)}"
                )
            clean_input = ", ".join(valid_cities)
            logger.info(f"City validation successful: {clean_input}")
        
        try:
            logger.debug("Updating database with new locations")
            await storage_service.update_system_settings(locations=clean_input)
            await update.effective_message.reply_text(f"✅ Updated cities to: {clean_input or 'All'}")
            
            if self.reset_trigger:
                self.reset_trigger()
            elif self.trigger_event:
                self.trigger_event.set()
                
            await self._render_menu(update)
            return MENU
        except Exception as e:
            logger.error(f"Error updating locations: {e}")
            await update.effective_message.reply_text("❌ Failed to update cities. Try again.")
            return EDIT_LOCS

    async def _handle_keys_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raw_input = update.effective_message.text or ""
        logger.info(f"Received keyword input: '{raw_input}'")
        
        # Sanitize input
        clean_input = bleach.clean(raw_input, strip=True)
        
        # Validate length
        if len(clean_input) > 500:
            await update.effective_message.reply_text(
                "❌ Input too long. Maximum 500 characters allowed."
            )
            return EDIT_KEYWORDS
        
        try:
            logger.debug("Updating database with new keywords")
            await storage_service.update_system_settings(search_keywords=clean_input)
            await update.effective_message.reply_text(f"✅ Updated keywords to: {clean_input}")
            
            if self.reset_trigger:
                self.reset_trigger()
            elif self.trigger_event:
                self.trigger_event.set()
                
            await self._render_menu(update)
            return MENU
        except Exception as e:
            logger.error(f"Error updating keywords: {e}")
            await update.effective_message.reply_text("❌ Failed to update keywords. Try again.")
            return EDIT_KEYWORDS

    async def _handle_cats_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raw_input = update.effective_message.text or ""
        logger.info(f"Received category input: '{raw_input}'")
        
        # Sanitize input
        clean_input = bleach.clean(raw_input, strip=True)
        
        # Validate length
        if len(clean_input) > 200:
            await update.effective_message.reply_text(
                "❌ Input too long. Maximum 200 characters allowed."
            )
            return EDIT_CATEGORIES
        
        # Clean and validate category IDs
        try:
            # Strip spaces and split by comma
            parts = [p.strip() for p in clean_input.split(",") if p.strip()]
            
            if not parts:
                raise ValueError("No IDs provided")
                
            invalid_ids = []
            valid_ids = []
            
            for part in parts:
                if part.isdigit():
                    val = int(part)
                    if 1 <= val <= 26:
                        valid_ids.append(str(val))
                    else:
                        invalid_ids.append(part)
                else:
                    invalid_ids.append(part)
            
            if invalid_ids:
                await update.effective_message.reply_text(
                    f"⚠️ <b>Invalid category ID(s):</b> {', '.join(invalid_ids)}\n"
                    "Allowed IDs are numbers from 1 to 26.\n"
                    "Try again or go back to menu.",
                    parse_mode="HTML"
                )
                return EDIT_CATEGORIES
                
            new_val = ",".join(valid_ids)
            await storage_service.update_system_settings(category_ids=new_val)
            await update.effective_message.reply_text(f"✅ Updated categories to: {new_val}")
            
        except Exception as e:
            logger.error(f"Error processing IDs: {e}")
            await update.effective_message.reply_text("⚠️ An error occurred while processing IDs. Make sure you enter only numbers separated by commas.")
            return EDIT_CATEGORIES
            
        if self.reset_trigger:
            self.reset_trigger()
        elif self.trigger_event:
            self.trigger_event.set()
            
        await self._render_menu(update)
        return MENU

    async def _handle_confirm_keywords_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle user confirmation of suggested keywords."""
        query = update.callback_query
        await query.answer()
        data = query.data
        
        if data == "apply_suggested":
            keywords = context.user_data.get("suggested_keywords")
            if keywords:
                await storage_service.update_system_settings(search_keywords=keywords)
                await query.edit_message_text(
                    f"✅ <b>Keywords updated to:</b>\n<code>{keywords}</code>\n\n"
                    "I will now use these for searching. Do you want to start a scan?",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚀 SEARCH NOW", callback_data="trigger_search")],
                        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]
                    ])
                )
                
                if self.reset_trigger:
                    self.reset_trigger()
                return MENU
            else:
                await query.edit_message_text("❌ Failed to retrieve suggestions. Please set them manually.")
                return MENU
                
        elif data == "edit_suggested":
            keywords = context.user_data.get("suggested_keywords", "")
            logger.info(f"Transitioning to EDIT_KEYWORDS state with keywords: {keywords}")
            await query.edit_message_text(
                "✏️ <b>Edit Suggested Keywords</b>\n\n"
                "Copy and modify the keywords below, then send them back to me:\n\n"
                f"<code>{keywords}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancel", callback_data="back_to_menu")]])
            )
            logger.info("Returning EDIT_KEYWORDS state")
            return EDIT_KEYWORDS
            
        elif data == "back_to_menu":
            await self._render_menu(update, edit=True)
            return MENU
            
        return MENU

    async def _handle_thresh_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raw_input = update.effective_message.text or ""
        
        # Sanitize input
        clean_input = bleach.clean(raw_input, strip=True)
        
        try:
            # Strip percentage sign if present
            clean_text = clean_input.replace("%", "").strip()
            val = int(clean_text)
            
            if 0 <= val <= 100:
                logger.info(f"Updating threshold to {val}")
                await storage_service.update_system_settings(match_threshold=val)
                logger.info(f"Threshold updated successfully to {val}")
                
                await update.effective_message.reply_text(f"✅ Updated threshold to: {val}%")
                
                if self.reset_trigger:
                    logger.info("Triggering reset after threshold change")
                    self.reset_trigger()
                elif self.trigger_event:
                    self.trigger_event.set()
                
                logger.info("Rendering menu after threshold update")
                await self._render_menu(update)
                logger.info("Menu rendered successfully")
                return MENU
            else:
                await update.effective_message.reply_text("⚠️ Enter a number between 0 and 100.")
                return EDIT_THRESHOLD
        except ValueError:
            logger.warning(f"Invalid threshold input: {clean_input}")
            await update.effective_message.reply_text("⚠️ Enter a valid number (e.g. 50).")
            return EDIT_THRESHOLD
        except Exception as e:
            logger.error(f"Error updating threshold: {e}", exc_info=True)
            await update.effective_message.reply_text("❌ Failed to update threshold. Try again.")
            return EDIT_THRESHOLD

    async def _stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command."""
        try:
            stats = await storage_service.get_statistics()
            last_scan = stats["last_scan"].strftime("%H:%M %d-%m-%Y") if stats["last_scan"] else "Never"
            
            # Average score
            avg_score = stats.get('average_score', 0)
            avg_score_text = f"📈 <b>Average Match Score:</b> {avg_score:.1f}%\n" if avg_score > 0 else ""
            
            # Format score distribution
            dist_text = ""
            if "score_distribution" in stats and stats["score_distribution"]:
                dist_lines = ["\n📊 <b>Offer Match Distribution (AI):</b>"]
                total_analyzed = stats['analyzed_offers']
                
                max_count = max(stats["score_distribution"].values()) if stats["score_distribution"] else 0
                
                for label, count in stats["score_distribution"].items():
                    if count >= 0: # Show all buckets if possible
                        # Visualization relative to the busiest bucket (max_count = 10 squares)
                        bar_length = int(count / max_count * 10) if max_count > 0 else 0
                        # Ensure at least 1 filled square if there are items but rounding turned it to 0
                        if count > 0 and bar_length == 0:
                            bar_length = 1
                            
                        bar = "■" * bar_length + "□" * (10 - bar_length)
                        dist_lines.append(f"<code>{label:>6}: {count:>3} {bar}</code>")
                
                if len(dist_lines) > 1:
                    dist_text = "\n".join(dist_lines) + "\n"
            
            # Top 10 offers
            top_offers = stats.get('top_offers', [])
            top_text = ""
            if top_offers:
                top_lines = ["\n🏆 <b>Top 10 Offers:</b>\n"]
                for i, offer in enumerate(top_offers[:10], 1):
                    score = int(offer['match_score'])
                    title = offer['title']
                    company = offer['company_name']
                    offer_url = offer.get('offer_url', '')
                    
                    # Medal emoji for top 3
                    if i == 1:
                        medal = "🥇"
                    elif i == 2:
                        medal = "🥈"
                    elif i == 3:
                        medal = "🥉"
                    else:
                        medal = f"  {i}."
                    
                    # Format: Medal Score% Title @ Company
                    #         🔗 Link
                    top_lines.append(f"{medal} <b>{score}%</b> {title}")
                    top_lines.append(f"     <i>@ {company}</i>")
                    if offer_url:
                        top_lines.append(f"     🔗 <a href='{offer_url}'>View offer</a>")
                    top_lines.append("")  # Empty line for spacing
                
                top_text = "\n".join(top_lines)

            msg = (
                "📊 <b>JobSniper Statistics</b>\n\n"
                f"📥 <b>Offers downloaded:</b> {stats['total_offers']}\n"
                f"🧠 <b>Analyzed by AI:</b> {stats['analyzed_offers']}\n"
                f"📨 <b>Alerts sent:</b> {stats['sent_notifications']}\n"
                f"{avg_score_text}"
                f"{dist_text}"
                f"{top_text}\n"
                f"🕒 <b>Last scan:</b> {last_scan}"
            )
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]]
            await update.effective_message.reply_html(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            await update.effective_message.reply_text("❌ Failed to retrieve statistics.")

    async def _mycv_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /mycv command - Show CV Menu."""
        await self._render_cv_menu(update)

    async def _handle_view_cv_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Dump the actual text of the CV."""
        cv_text = matcher_service.cv_text
        if not cv_text:
            await update.effective_message.reply_text("❌ I don't have your CV saved.\nSend a PDF file.")
            return

        await update.effective_message.reply_text(f"📄 <b>Your CV ({len(cv_text)} characters):</b>", parse_mode="HTML")
        
        # Split text into chunks of 4000 characters (Telegram limit is 4096)
        chunk_size = 4000
        for i in range(0, len(cv_text), chunk_size):
            chunk = cv_text[i:i + chunk_size]
            await update.effective_message.reply_text(chunk)
            
        await update.effective_message.reply_text("✅ End of uploaded CV.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to CV menu", callback_data="show_cv")]
        ]))

    async def _reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /reset command - ask for confirmation."""
        text = (
            "⚠️ <b>Confirm Reset</b>\n\n"
            "This will reset the analysis status for ALL offers in the database.\n"
            "• All offers will be treated as new\n"
            "• High matches will be re-notified if found again\n"
            "• Current scanning cycle will be stopped\n\n"
            "Are you sure you want to proceed?"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Reset All", callback_data="do_full_reset"),
                InlineKeyboardButton("❌ No, Cancel", callback_data="back_to_menu"),
            ]
        ]
        
        await update.effective_message.reply_html(
            text, 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MENU # Keep in MENU to handle buttons
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show detailed help message explaining AI and features."""
        help_text = (
            "🤖 <b>JobSniper - Your AI Recruiter</b>\n\n"
            
            "<b>🧠 How the AI Magic Works:</b>\n"
            "Unlike standard job boards that just match keywords (which often fails), "
            "I use <b>Advanced AI (GPT-4o)</b> to read every job offer like a human recruiter.\n\n"
            "1. <b>Full Analysis:</b> I read the entire job description, not just the title.\n"
            "2. <b>Contextual Matching:</b> I compare it against your <b>uploaded CV</b>. I understand that 'Python experience' is related to 'Django' or 'FastAPI'.\n"
            "3. <b>Scoring (0-100%):</b> I assign a match score based on hard skills AND soft skills.\n"
            "4. <b>Filtering:</b> I only notify you if the score is above your <b>Threshold</b>.\n\n"
            
            "<b>🎮 Control Panel Functions:</b>\n"
            "• <b>🚀 SEARCH NOW:</b> Forces an immediate scan of all sources.\n"
            "• <b>🛑 STOP SEARCH:</b> Completely pauses the bot. No notifications will be sent until you resume.\n"
            "• <b>📊 Statistics:</b> Shows how many offers were scanned and the distribution of match scores.\n"
            "• <b>📂 My CV:</b> View a summary of what the AI knows about you from your PDF.\n"
            "• <b>🌐 Sources:</b> Enable/disable specific job boards (JustJoinIT, RemoteOK, etc.).\n\n"
            
            "<b>⚙️ Settings & Filters:</b>\n"
            "• <b>🎯 Threshold:</b> Minimum AI score required to get a notification (e.g., 70%). Lower it to see more offers.\n"
            "• <b>🌍 Cities / 🏠 Remote:</b> Traditional location filters.\n"
            "• <b>🔍 Keywords:</b> <i>Speed up the process!</i> These are pre-filters. If you set 'Python', I only use AI to analyze offers containing 'Python'.\n\n"
            
            "<b>💡 Pro Tip:</b>\n"
            "If you get too many weak matches, increase the <b>Threshold</b> to 80%.\n"
            "If you get nothing, lower the <b>Threshold</b> to 40% or check your <b>Keywords</b>."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.effective_message:
            # If triggered by button, edit the message for smoother UX
            if update.callback_query:
                try:
                    await update.effective_message.edit_text(text=help_text, reply_markup=reply_markup, parse_mode="HTML")
                except Exception:
                   # Fallback if edit fails (e.g. message too old)
                   await update.effective_message.reply_html(help_text, reply_markup=reply_markup)
            else:
                await update.effective_message.reply_html(help_text, reply_markup=reply_markup)

    async def _handle_cv_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle PDF file upload."""
        document = update.message.document
        
        # Verify it's a PDF
        if document.mime_type != "application/pdf":
            await update.effective_message.reply_text("⚠️ Please send a PDF file.")
            return
            
        try:
            await update.effective_message.reply_text("📥 Downloading your CV...")
            
            # Download file
            new_file = await document.get_file()
            cv_path = Path(settings.cv_path)
            cv_path.parent.mkdir(parents=True, exist_ok=True)
            
            await new_file.download_to_drive(cv_path)
            logger.info(f"CV uploaded and saved to {cv_path}")
            
            # Reload matcher
            success = await matcher_service.reload_cv()
            
            if success:
                # 🧠 AI Keyword Suggestion Logic
                suggested_keywords = await matcher_service.extract_keywords()
                
                if suggested_keywords:
                    context.user_data["suggested_keywords"] = suggested_keywords
                    
                    markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Apply to Filters", callback_data="apply_suggested")],
                        [InlineKeyboardButton("✏️ Edit & Apply", callback_data="edit_suggested")],
                        [InlineKeyboardButton("❌ Keep Current", callback_data="back_to_menu")]
                    ])
                    
                    await update.effective_message.reply_html(
                        "✅ <b>CV has been updated!</b>\n\n"
                        "🧠 <b>AI Suggestion:</b> I found these tech keywords in your CV:\n"
                        f"<code>{suggested_keywords}</code>\n\n"
                        "Would you like to use them as your primary search filters?",
                        reply_markup=markup
                    )
                    return CONFIRM_KEYWORDS
                else:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Set Filters", callback_data="back_to_menu")]])
                    await update.effective_message.reply_html(
                        "✅ <b>CV has been updated!</b>\n"
                        "Now I will use the new version for offer analysis.\n\n"
                        "🛑 <b>Current scan stopped.</b>\n"
                        "Press 🚀 <b>SEARCH NOW</b> when you are ready to scan with the new CV.",
                        reply_markup=markup
                    )
            else:
                await update.effective_message.reply_text("❌ File saved, but failed to read its content.")
                
        except Exception as e:
            logger.error(f"Error handling CV upload: {e}", exc_info=True)
            await update.effective_message.reply_text(f"❌ Error saving CV: {str(e)}")

    async def send_job_alert(
        self,
        job_title: str,
        company_name: str,
        match_score: float,
        match_reason: str,
        offer_url: str,
        source: Optional[str] = None,
        salary_from: Optional[int] = None,
        salary_to: Optional[int] = None,
        salary_currency: Optional[str] = None,
        remote: bool = False,
        city: Optional[str] = None,
        skills: Optional[list[str]] = None,
    ) -> bool:
        """Send a job alert to the configured chat ID."""
        # 🛡️ IMMEDIATE STOP CHECK
        if self.search_manually_stopped:
            logger.info(f"🚫 Notification aborted for '{job_title}' - search is manually stopped")
            return False
            
        if not self.app:
            logger.warning("Bot not initialized, cannot send alert")
            return False
            
        try:
            message = self._format_message(
                job_title=job_title,
                company_name=company_name,
                match_score=match_score,
                match_reason=match_reason,
                offer_url=offer_url,
                source=source,
                salary_from=salary_from,
                salary_to=salary_to,
                salary_currency=salary_currency,
                remote=remote,
                city=city,
                skills=skills,
            )
            
            keyboard = [
                [InlineKeyboardButton("🔗 Open Offer", url=offer_url)],
                [InlineKeyboardButton("⬅️ Go to Control Panel", callback_data="back_to_menu")]
            ]
            markup = InlineKeyboardMarkup(keyboard)
            
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False,
                reply_markup=markup,
            )
            
            logger.info(f"Sent alert for: {job_title}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}", exc_info=True)
            return False

    async def send_test_message(self) -> bool:
        """Send a test message."""
        # Disabled: User finds this message unnecessary
        logger.info("Test message disabled - bot starting silently")
        return True
            
    # Include the previously defined _format_message and send_error_alert methods here
    def _format_message(self, **kwargs) -> str:
        # (Same implementation as before, reused to keep formatting consistent)
        # For brevity in this replacement, I'll copy the logic from previous step
        # But to be clean, I will re-implement it briefly or assume it's kept if I use replace correctly.
        # Since I'm replacing the whole class, I must re-include helper methods.
        
        job_title = kwargs.get('job_title')
        company_name = kwargs.get('company_name')
        match_score = kwargs.get('match_score')
        match_reason = kwargs.get('match_reason')
        offer_url = kwargs.get('offer_url')
        salary_from = kwargs.get('salary_from')
        salary_to = kwargs.get('salary_to')
        salary_currency = kwargs.get('salary_currency')
        remote = kwargs.get('remote')
        city = kwargs.get('city')
        skills = kwargs.get('skills')

        if match_score >= 90: score_emoji = "🔥"
        elif match_score >= 80: score_emoji = "⭐"
        else: score_emoji = "✅"
        
        # Source badge
        source = kwargs.get('source', 'JJIT')
        source_badges = {
            'RemoteOK': '🌐 RemoteOK',
            'Remotive': '🌐 Remotive',
            'WWR': '🌐 WeWorkRemotely',
            'Arbeitnow': '🌐 Arbeitnow',
            'JJIT': '🇵🇱 JustJoinIT',
        }
        source_badge = source_badges.get(source, f'📍 {source}')
        
        lines = [
            f"{score_emoji} <b>NEW OFFER - {int(match_score)}% MATCH</b> {score_emoji}",
            f"{source_badge}",
            "",
            f"<b>Position:</b> {job_title}",
            f"<b>Company:</b> {company_name}",
        ]
        
        if remote: lines.append(f"<b>Location:</b> 🌍 Remote")
        elif city: lines.append(f"<b>Location:</b> {city}")
        
        if salary_from or salary_to:
            salary_parts = []
            if salary_from: salary_parts.append(f"{salary_from:,}")
            if salary_to:
                if salary_from: salary_parts.append(f" - {salary_to:,}")
                else: salary_parts.append(f"up to {salary_to:,}")
            salary_text = "".join(salary_parts)
            if salary_currency: salary_text += f" {salary_currency}"
            lines.append(f"<b>Salary:</b> {salary_text}")
        
        if skills and len(skills) > 0:
            skills_text = ", ".join(skills[:5])
            if len(skills) > 5: skills_text += f" +{len(skills) - 5} more"
            lines.append(f"<b>Technologies:</b> {skills_text}")
        
        lines.extend([
            "",
            f"<b>Why it matches:</b>",
            f"<i>{match_reason}</i>",
            "",
            f"🔗 <a href='{offer_url}'>View offer</a>",
        ])
        return "\n".join(lines)

    async def send_error_alert(self, error_message: str) -> None:
        if not self.app: return
        try:
            message = f"⚠️ <b>JobSniper Error</b>\n\n{error_message}"
            await self.app.bot.send_message(chat_id=self.chat_id, text=message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send error alert: {e}")

    def set_trigger_event(self, event: asyncio.Event) -> None:
        """Set event to trigger main loop processing."""
        self.trigger_event = event
    
    def set_stop_search_handler(self, handler_func: Callable) -> None:
        """Set the handler function to stop current search."""
        self.stop_search_handler = handler_func

notification_service = NotificationService()
