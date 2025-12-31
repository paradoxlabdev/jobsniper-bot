# JobSniper Migration Guide - All Fixes Applied

## Overview
This guide covers the migration process for all 12 implemented fixes in JobSniper.

---

## Pre-Migration Checklist

1. **Backup your database**
   ```bash
   docker-compose exec db pg_dump -U jobsniper -d jobsniper_db > backup_$(date +%Y%m%d).sql
   ```

2. **Stop the current application**
   ```bash
   docker-compose down
   ```

3. **Update dependencies**
   ```bash
   pip install -r requirements.txt
   # OR rebuild Docker image
   docker-compose build
   ```

---

## Database Migration

The timezone-aware datetime migration is **automatic** and runs on startup via `core/database.py`. However, if you prefer manual control:

### Manual Migration (Optional)

Connect to PostgreSQL:
```bash
docker-compose exec db psql -U jobsniper -d jobsniper_db
```

Run the following SQL:
```sql
-- Migrate job_offers table
ALTER TABLE job_offers 
ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE 
USING created_at AT TIME ZONE 'UTC';

ALTER TABLE job_offers 
ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE 
USING updated_at AT TIME ZONE 'UTC';

ALTER TABLE job_offers 
ALTER COLUMN published_at TYPE TIMESTAMP WITH TIME ZONE 
USING published_at AT TIME ZONE 'UTC';

ALTER TABLE job_offers 
ALTER COLUMN notified_at TYPE TIMESTAMP WITH TIME ZONE 
USING notified_at AT TIME ZONE 'UTC';

-- Migrate processing_logs table
ALTER TABLE processing_logs 
ALTER COLUMN started_at TYPE TIMESTAMP WITH TIME ZONE 
USING started_at AT TIME ZONE 'UTC';

ALTER TABLE processing_logs 
ALTER COLUMN completed_at TYPE TIMESTAMP WITH TIME ZONE 
USING completed_at AT TIME ZONE 'UTC';

-- Migrate system_settings table
ALTER TABLE system_settings 
ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE 
USING updated_at AT TIME ZONE 'UTC';

-- Verify migrations
\d+ job_offers
\d+ processing_logs
\d+ system_settings
```

---

## Deployment Steps

### 1. Pull Changes (if using Git)
```bash
git pull origin main
```

### 2. Rebuild and Start
```bash
docker-compose up -d --build
```

### 3. Monitor Logs
```bash
docker-compose logs -f app
```

**Look for:**
- ✅ `Timezone-aware datetime migration completed successfully`
- ✅ `Database initialized successfully`
- ✅ `JobSniper initialized successfully`
- ✅ `Fetched X offers from API across Y pages` (should show multiple pages now)

---

## Expected Behavior Changes

### 1. **Keyword Filtering (60% threshold)**
- **Before:** ALL keywords required → many "0 match criteria"
- **After:** 60% of keywords required → more matches

**Test:**
```
Keywords: "Python, Senior, Backend"
Before: Offer MUST have all 3 words
After: Offer needs 2 out of 3 (60%)
```

### 2. **Pagination**
- **Before:** Max 100 offers per scan
- **After:** Up to 1000 offers (10 pages)

**Expected logs:**
```
Fetched page 1: 100 offers
Fetched page 2: 100 offers
...
Fetched 532 offers from API across 6 pages, 127 match criteria
```

### 3. **Timezone Handling**
- **Before:** Naive datetimes (risk of timezone bugs)
- **After:** All datetimes are timezone-aware (UTC)

### 4. **Rate Limiting**
- **Before:** All OpenAI requests in parallel (possible rate limit errors)
- **After:** Max 5 concurrent requests (Semaphore)

### 5. **Input Validation**
- **Before:** No sanitization (XSS/injection risk)
- **After:** All user inputs sanitized with bleach library

---

## Verification Tests

### Test 1: Keyword Filtering
```bash
# In Telegram bot:
1. /menu
2. Edit Keywords → Enter: "Python, Senior, Remote"
3. SEARCH NOW
4. Check logs: should see more matches than before
```

### Test 2: Pagination
```bash
# Monitor logs during scan:
docker-compose logs -f app | grep "Fetched page"

# Should see multiple pages being fetched
```

### Test 3: Input Validation
```bash
# In Telegram bot:
1. /menu
2. Edit Cities → Try entering: "<script>alert('test')</script>"
3. Should be sanitized automatically
```

### Test 4: Timezone Consistency
```bash
# Check database:
docker-compose exec db psql -U jobsniper -d jobsniper_db -c \
  "SELECT created_at, timezone('UTC', created_at) FROM job_offers LIMIT 5;"
```

---

## Rollback Procedure (if needed)

### 1. Restore Database Backup
```bash
docker-compose exec -T db psql -U jobsniper -d jobsniper_db < backup_YYYYMMDD.sql
```

### 2. Revert Code Changes
```bash
git reset --hard <previous_commit_hash>
docker-compose up -d --build
```

---

## Performance Improvements

### Expected Gains:
- **10x more offers fetched** (100 → 1000+)
- **3-5x more matches** (due to flexible keyword threshold)
- **Faster AI processing** (rate limiting prevents timeouts)
- **Memory leak prevention** (ConversationHandler timeout)
- **No more race conditions** (asyncio.Lock protection)

---

## Troubleshooting

### Issue: "0 match criteria" still appearing
**Solution:** Check your keywords are not too specific. Try reducing number of keywords or verify they match actual offer text.

### Issue: Migration fails with "column already exists"
**Solution:** This is expected if migration already ran. The code is idempotent.

### Issue: OpenAI rate limit errors
**Solution:** Semaphore is set to 5. Reduce further in `services/matcher.py`:
```python
self._openai_semaphore = asyncio.Semaphore(3)  # Change from 5 to 3
```

### Issue: Too many offers being analyzed
**Solution:** Adjust constant in `main.py`:
```python
MAX_OFFERS_PER_ANALYSIS_CYCLE = 30  # Reduce from 50
```

---

## Maintenance Notes

### When to Bump PROMPT_VERSION
Change `PROMPT_VERSION` in `services/matcher.py` when you modify:
- AI prompt text
- Scoring criteria
- System message
- Temperature or max_tokens

This invalidates the cache automatically.

### Monitoring
Watch these logs regularly:
```bash
# Check for errors
docker-compose logs app | grep ERROR

# Check pagination working
docker-compose logs app | grep "Fetched page"

# Check match rates
docker-compose logs app | grep "match criteria"
```

---

## Contact & Support

If you encounter issues:
1. Check logs: `docker-compose logs -f app`
2. Verify database migration: `\d+ job_offers` in psql
3. Test with single keyword first to verify filtering works
4. Review this migration guide for specific solutions

---

**Migration completed successfully if:**
- ✅ No errors in logs
- ✅ Multiple pages being fetched (logs show "Fetched page 1, 2, 3...")
- ✅ More offers matching than before
- ✅ Database columns show TIMESTAMP WITH TIME ZONE
- ✅ User inputs are sanitized (try entering HTML tags)

Good luck with the migration! 🚀
