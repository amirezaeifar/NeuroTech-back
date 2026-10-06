# Event management

Open `/admin/events`. Existing site roles apply: content managers and admins submit editorial changes to the principal approval queue; super admins save/publish directly. Live session controls and moderation are immediate operational actions for staff and assigned speakers.

## Before an event

1. Add the Persian and English title, summary, description and host. Select online or onsite, the venue, capacity, start/end times and display timezone. The date inputs use the administrator's device timezone; the API stores UTC and event pages display the event timezone. Empty capacity means unlimited.
2. Select registered speakers by name. These users can control the session without booking a seat.
3. Add an HTTPS playback URL and ordered live steps. An upcoming online event can be saved before its stream is ready. A stream URL is required to start a live session.
4. Save and publish. Visitors must sign in before confirming a reservation. Repeated confirmations use the same reservation; simultaneous bookings cannot exceed capacity. Cancel a participant from **Live & reservations** to release their seat and revoke room access. Capacity cannot be reduced below the confirmed count.

## During the live session

Use **Live & reservations** to start/end the session, advance steps, pause/reopen chat or questions, mark questions answered, remove messages/questions, and manage attendees. Attendee presence and conversations refresh every five seconds; presence expires after 45 seconds without a heartbeat. Ending the session removes the stream and closes posting/voting. Unpublishing or cancelling revokes room access.

The elapsed clock starts when the session is actually switched to **Live**. Each agenda step records its own elapsed duration; switching steps saves the time already spent, so a page refresh does not reset it. Staff can upload a document in the live control room, and it appears in **Clinical Documents** in both languages after saving or required approval.

The existing live hub plays embedded YouTube/Vimeo/Aparat video and direct MP4/WebM or HLS (`.m3u8`) streams. HLS playback uses native support where available and [HLS.js](https://hlsjs.video-dev.org/api-docs/hls.js.hls) elsewhere. Configure cross-origin playback/CORS and embedding permissions at the stream provider. For OBS, publish to a streaming provider and enter that provider's HTTPS playback URL, **not** its RTMP ingest address or secret stream key.

This implementation supplies the gated event room and player; it does not provision a streaming service or broadcast the host's camera. A real provider URL is needed to verify an actual broadcast. The URL is withheld from public catalogue responses and only returned to booked users/hosts during a live session. For protection against a participant sharing that external URL, configure signed playback URLs/domain restrictions at the chosen streaming provider.

Country totals use a local MaxMind-compatible country database set by `GEOIP_DATABASE_PATH`. Install the Python dependencies and set this variable to the absolute path of a current `.mmdb` file on the server. If a reverse proxy is used, set `TRUSTED_PROXY_IPS` to the proxy's IP so the server can read the visitor's forwarded IP safely. Without a database, attendees appear as “Unknown”; their location is not fabricated.

## After the event

Ending a live event sets **Completed** and makes it appear in the past-events list. **Page content** manages separate Persian/English gallery captions, recordings, downloadable documents, agenda, FAQ and closing note. Upload or paste media URLs, reorder/remove rows, then save. Local uploads support the existing 100 MB limit; use a hosted video URL for larger recordings. Uploaded public files are publicly accessible; removing a row detaches it from the event without deleting a shared file.

The original public page layout remains, with its gallery, lightbox, descriptions, FAQ and download cards connected to saved content. Empty sections are hidden. **Remove from site** archives/unpublishes the event; it is distinct from **Completed**, which keeps the past-event page available.

## Setup and verification

Install backend dependencies (including `tzdata` for Windows) and frontend dependencies, then run `python -m alembic upgrade head` **before restarting the API**. Migration `20260928_0023` adds the live timing columns; serving the new code against revision `20260928_0022` causes event and admin requests to fail with an unknown-column database error.

Relevant tests: `tests/api/test_event_management.py`, `tests/api/test_articles_event_live.py`, `tests/api/test_catalog_events_files.py`, and `tests/test_migrations.py`. Browser verification should include admin save/reopen, upload/download, both locales, attendee login/reservation, live controls and the configured stream provider.
# Embedded live streams

The event hub accepts a YouTube live URL and displays it through the
`youtube-nocookie.com` embedded player. A YouTube embed can still expose YouTube
branding or links controlled by YouTube; the application cannot guarantee that
viewers will be unable to navigate to YouTube. For a stream that stays entirely
within NeuroTech, use a direct HTTPS HLS/video URL from a streaming provider
whose player and access policy you control.
