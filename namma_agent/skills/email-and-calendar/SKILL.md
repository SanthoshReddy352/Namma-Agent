---
name: email-and-calendar
description: >
  Triage the user's Gmail and Google Calendar: summarize the inbox, find a
  message, draft replies, check the agenda, schedule events. Use when the user
  asks about their email, inbox, a message from someone, their schedule,
  meetings, or wants to send an email or create an event.
platforms: [linux, macos, windows]
version: 1.0.0
category: productivity
prerequisites:
  commands: [gws]
metadata:
  hermes:
    tags: [email, gmail, calendar, schedule]
---

# Email and Calendar

These tools act on the user's real accounts, so read freely and write only
with a clear go-ahead.

## Procedure

1. **Inbox triage**: `gmail_list` (recent / unread), open the important ones
   with `gmail_read`, and report a table: from · subject · what they need ·
   suggested action.
2. **Replies**: draft with the `writing` approach, show the draft, and call
   `gmail_send` only after the user approves the exact text and recipient.
3. **Agenda**: `calendar_agenda` for the asked range; present it as a time
   table and flag conflicts or back-to-back meetings.
4. **Scheduling**: confirm title, time (with time zone), duration and invitees,
   then `calendar_create_event`.

## Gotchas

- If `gws` isn't set up, say so and point to `gws auth login`.
- Never forward or send content the user hasn't seen.
