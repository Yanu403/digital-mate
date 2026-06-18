# 📅 Notion Setup Guide

This guide walks you through setting up Notion databases for Digital Mate's content calendar and campaign tracker features.

## Prerequisites

- A Notion account (free or paid)
- Admin access to a Notion workspace

---

## Step 1: Create a Notion Integration

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **"+ New integration"**
3. Fill in the details:
   - **Name**: `Digital Mate` (or any name you prefer)
   - **Associated workspace**: Select your workspace
   - **Type**: Internal
4. Click **"Submit"**
5. Copy the **Internal Integration Token** — this is your `NOTION_API_KEY`

> ⚠️ Keep this token secret! Never share it or commit it to version control.

---

## Step 2: Create the Content Calendar Database

1. In Notion, create a new page (or navigate to where you want the database)
2. Create a new **Database — Table** view
3. Name it: **Content Calendar**
4. Add the following properties:

| Property Name | Type | Notes |
|---------------|------|-------|
| **Title** | Title | Content/post title |
| **Date** | Date | Scheduled publish date |
| **Platform** | Select | Options: Instagram, Twitter/X, LinkedIn, Facebook, TikTok, YouTube, Blog |
| **Content Type** | Select | Options: Post, Reel, Story, Thread, Article, Video, Carousel |
| **Status** | Status | Options: Planned, Draft, Scheduled, Published |
| **Caption** | Text (Rich text) | The post caption/text |
| **Hashtags** | Text (Rich text) | Associated hashtags |
| **Notes** | Text (Rich text) | Additional notes or instructions |

### Example Entries

| Title | Date | Platform | Content Type | Status |
|-------|------|----------|-------------|--------|
| Product launch teaser | 2024-01-15 | Instagram | Reel | Planned |
| Industry tips thread | 2024-01-17 | Twitter/X | Thread | Draft |
| Behind the scenes | 2024-01-19 | Instagram | Story | Scheduled |

---

## Step 3: Create the Campaign Tracker Database

1. Create another **Database — Table** view
2. Name it: **Campaign Tracker**
3. Add the following properties:

| Property Name | Type | Notes |
|---------------|------|-------|
| **Name** | Title | Campaign name |
| **Status** | Select | Options: Planned, Active, Paused, Completed |
| **Start Date** | Date | Campaign start date |
| **End Date** | Date | Campaign end date |
| **Budget** | Number | Total budget (use currency formatting) |
| **Reach** | Number | Total reach/impressions |
| **Engagement** | Number | Total engagements (likes, comments, shares) |
| **Conversions** | Number | Total conversions |
| **Channel** | Select | Primary channel: Social, Email, Search, Display, Multi-channel |
| **Notes** | Text (Rich text) | Campaign notes and observations |

### Example Entries

| Name | Status | Start Date | End Date | Budget | Reach |
|------|--------|-----------|----------|--------|-------|
| Q1 Product Launch | Active | 2024-01-01 | 2024-03-31 | 5000 | 50000 |
| Summer Sale | Planned | 2024-06-01 | 2024-06-30 | 2000 | — |

---

## Step 4: Share Databases with Your Integration

For each database you created:

1. Open the database page in Notion
2. Click the **"..."** menu (top-right corner)
3. Click **"Connections"** or **"Add connections"**
4. Search for your integration name (e.g., "Digital Mate")
5. Click to **add** it
6. Confirm the connection

> 🔑 **Important**: You must share EACH database with your integration. If you forget this step, the bot won't be able to read your data.

---

## Step 5: Get Database IDs

You need the database IDs to configure Digital Mate:

### Method 1: From the URL

1. Open the database in Notion (full page view, not embedded)
2. Look at the URL in your browser:
   ```
   https://www.notion.so/myworkspace/abc123def456...?v=...
   ```
3. The database ID is the 32-character hex string after the last `/` and before `?`:
   ```
   abc123def456...  (32 characters, no dashes)
   ```

### Method 2: From the Share Menu

1. Click **"Share"** on the database page
2. Click **"Copy link"**
3. Extract the ID from the URL as described above

### Format the ID

The database ID should be formatted as a 32-character hex string (no dashes):
```
abc123def456789012345678abcdef12
```

---

## Step 6: Configure Digital Mate

Add the values to your `.env` file:

```env
# Notion Integration Token (from Step 1)
NOTION_API_KEY=ntn_your_integration_token_here

# Content Calendar Database ID (from Step 5)
NOTION_CONTENT_CALENDAR_DB=abc123def456789012345678abcdef12

# Campaign Tracker Database ID (from Step 5)
NOTION_CAMPAIGN_TRACKER_DB=fedcba9876543210fedcba9876543210
```

---

## Step 7: Verify

1. Start Digital Mate: `python -m digital_mate`
2. Check the startup banner shows "Notion ✅"
3. Try the `/calendar` command to see your content calendar
4. Try the `/report` command for campaign data

---

## Troubleshooting

### Bot says "Notion integration not configured"
- Check that all three environment variables are set in `.env`
- Ensure there are no extra spaces or quotes around the values

### Bot can't read database
- Make sure you shared EACH database with your integration (Step 4)
- Verify the database IDs are correct (32 hex characters, no dashes)
- Check that the property names match exactly (case-sensitive)

### Empty results from /calendar
- Ensure your Content Calendar has entries with dates
- The property names must match: Title, Date, Platform, Content Type, Status
- Check that dates are set (not empty) for entries to appear

### API errors
- Verify your integration token is valid at [notion.so/my-integrations](https://notion.so/my-integrations)
- Ensure your integration hasn't been disconnected from the workspace
- Check the bot logs for specific error messages (`--log-level DEBUG`)

---

## Property Name Reference

Digital Mate looks for these exact property names. If your database uses different names, either rename the properties in Notion or update the property names in `digital_mate/integrations/notion_client.py`.

### Content Calendar
- `Title` (title type)
- `Date` (date type)
- `Platform` (select type)
- `Content Type` (select type)
- `Status` (status or select type)

### Campaign Tracker
- `Name` (title type)
- `Status` (select type)
- `Start Date` (date type)
- `End Date` (date type)
- `Budget` (number type)
- `Reach` (number type)
- `Engagement` (number type)
- `Conversions` (number type)
