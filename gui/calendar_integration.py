"""
Google Calendar integration for Transcript Recorder.

Provides OAuth2 authentication, event fetching, and parsing utilities
to populate meeting details from Google Calendar events.

All Google API imports are guarded so the rest of the application works
even when the google-auth / google-api-python-client packages are not
installed.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("TranscriptRecorder")

# ---------------------------------------------------------------------------
# Optional Google imports — guarded so the app still loads without them
# ---------------------------------------------------------------------------
_HAS_GOOGLE = False
try:
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    _HAS_GOOGLE = True
except Exception as _exc:
    import sys as _sys
    print(f"[Calendar] Google API import failed: {_exc}", file=_sys.stderr)
    logger.warning(f"Google API libraries not available: {_exc}")


# Google Calendar API scope — read-only
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Event types to exclude from the picker
_EXCLUDED_EVENT_TYPES = {"workingLocation", "fromGmail", "outOfOffice"}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class CalendarConfig:
    """Settings for the Google Calendar integration."""
    enabled: bool = False
    client_secret_path: str = ""
    # Token is always stored in a fixed location — not user-configurable
    token_path: str = ""

    def is_ready(self) -> bool:
        """Return True when the integration can attempt API calls."""
        return (
            _HAS_GOOGLE
            and self.enabled
            and bool(self.client_secret_path)
            and os.path.isfile(self.client_secret_path)
        )

    def has_token(self) -> bool:
        return bool(self.token_path) and os.path.isfile(self.token_path)


def calendar_config_from_dict(
    raw: Dict[str, Any],
    token_dir: Path,
) -> CalendarConfig:
    """Build a CalendarConfig from the ``google_calendar`` section of config.json."""
    token_dir.mkdir(parents=True, exist_ok=True)
    return CalendarConfig(
        enabled=raw.get("enabled", False),
        client_secret_path=raw.get("client_secret_path", ""),
        token_path=str(token_dir / "token.json"),
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def authenticate(config: CalendarConfig) -> Any:
    """Authenticate with Google via OAuth2 and return Credentials.

    On first run (or after token expiry) this opens a browser window for
    consent.  The token is persisted at ``config.token_path`` so that
    subsequent calls succeed silently.

    Raises ``RuntimeError`` on any failure.
    """
    if not _HAS_GOOGLE:
        raise RuntimeError("Google API libraries are not installed")

    creds = None

    # Load existing token
    if config.has_token():
        try:
            creds = Credentials.from_authorized_user_file(config.token_path, SCOPES)
        except Exception as exc:
            logger.warning(f"Calendar: failed to load token: {exc}")
            creds = None

    # Refresh or run full OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.isfile(config.client_secret_path):
                raise RuntimeError(
                    f"Client secret file not found: {config.client_secret_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                config.client_secret_path, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Persist token
        token_dir = os.path.dirname(config.token_path)
        if token_dir:
            os.makedirs(token_dir, exist_ok=True)
        with open(config.token_path, "w") as f:
            f.write(creds.to_json())
        logger.info(f"Calendar: token saved to {config.token_path}")

    return creds


# ---------------------------------------------------------------------------
# Event fetching
# ---------------------------------------------------------------------------

def fetch_events_for_date(
    creds: Any,
    target_date: Optional[datetime.date] = None,
) -> List[Dict[str, Any]]:
    """Fetch ALL events for *target_date* from the user's primary calendar.

    If *target_date* is ``None``, today is used.  Returns every event
    without any filtering (all-day, declined, etc. are all included).
    Use :func:`filter_events` to apply display filters.
    """
    if not _HAS_GOOGLE:
        return []

    service = build("calendar", "v3", credentials=creds)

    if target_date is None:
        target_date = datetime.date.today()

    tz = datetime.datetime.now().astimezone().tzinfo
    start_of_day = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=tz)
    end_of_day = start_of_day + datetime.timedelta(days=1)

    all_events: List[dict] = []
    page_token = None

    while True:
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            )
            .execute()
        )
        all_events.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    logger.info(f"Calendar: fetched {len(all_events)} raw event(s) for {target_date}")
    return all_events


# Keep the old name as a convenience alias
def fetch_todays_events_raw(creds: Any) -> List[Dict[str, Any]]:
    """Fetch ALL of today's events (convenience wrapper)."""
    return fetch_events_for_date(creds)


def is_all_day(event: Dict[str, Any]) -> bool:
    """Return True if *event* is an all-day event (no dateTime, only date)."""
    return "dateTime" not in event.get("start", {})


def filter_events(
    events: List[Dict[str, Any]],
    *,
    include_all_day: bool = False,
    include_declined: bool = False,
) -> List[Dict[str, Any]]:
    """Apply standard display filters to raw calendar events.

    For **timed** events, always excludes non-meeting event types
    (workingLocation, fromGmail, outOfOffice).

    When ``include_all_day`` is True, **all** all-day events are shown
    regardless of event type — this ensures multi-day events like hotel
    bookings (``fromGmail``) and OOO blocks (``outOfOffice``) appear
    when the user explicitly asks to see all-day events.
    """
    filtered: List[dict] = []
    excluded_type_count = 0
    allday_excluded_count = 0
    declined_excluded_count = 0
    for ev in events:
        allday = is_all_day(ev)

        # --- All-day event handling ---
        if allday:
            if include_all_day:
                # Show all all-day events (including fromGmail, outOfOffice, etc.)
                filtered.append(ev)
            else:
                allday_excluded_count += 1
            continue

        # --- Timed event handling ---
        # Exclude non-meeting event types for timed events
        evt_type = ev.get("eventType", "default")
        if evt_type in _EXCLUDED_EVENT_TYPES:
            excluded_type_count += 1
            logger.debug(
                f"filter_events: excluding timed '{ev.get('summary', '?')}' "
                f"(eventType={evt_type})"
            )
            continue

        # Declined filter
        if not include_declined and _is_declined(ev):
            declined_excluded_count += 1
            continue

        filtered.append(ev)

    logger.debug(
        f"filter_events: {len(events)} raw -> {len(filtered)} shown "
        f"(excluded_type={excluded_type_count}, allday_hidden={allday_excluded_count}, "
        f"declined_hidden={declined_excluded_count}, "
        f"include_all_day={include_all_day}, include_declined={include_declined})"
    )
    return filtered


def fetch_todays_events(creds: Any) -> List[Dict[str, Any]]:
    """Fetch today's events from the user's primary calendar.

    Returns the raw Google Calendar event dicts, filtered to exclude
    all-day events, declined events, and non-meeting event types.
    """
    raw = fetch_todays_events_raw(creds)
    filtered = filter_events(raw)
    logger.info(f"Calendar: {len(filtered)} timed event(s) after filtering "
                f"(from {len(raw)} total)")
    return filtered


def _is_declined(event: Dict[str, Any]) -> bool:
    """Return True if the current user declined this event."""
    for att in event.get("attendees", []):
        if att.get("self"):
            return att.get("responseStatus") == "declined"
    return False


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

# Each entry: (platform_display_name, source_key, list_of_regex_patterns)
# Patterns are matched against the event description AND location fields.
PLATFORM_PATTERNS: List[Tuple[str, str, List[re.Pattern]]] = [
    (
        "Zoom",
        "zoom",
        [
            re.compile(r"https://[\w.-]*zoom\.us/j/\d+", re.IGNORECASE),
            re.compile(r"https://[\w.-]*zoom\.us/my/[\w.-]+", re.IGNORECASE),
            re.compile(r"Join Zoom Meeting", re.IGNORECASE),
        ],
    ),
    (
        "Microsoft Teams",
        "msteams",
        [
            re.compile(
                r"https://teams\.microsoft\.com/(?:l/meetup-join|meet)/\S+",
                re.IGNORECASE,
            ),
            re.compile(r"Microsoft Teams [Mm]eeting", re.IGNORECASE),
        ],
    ),
    (
        "WebEx",
        "webex",
        [
            re.compile(r"https://[\w.-]*webex\.com/\S+", re.IGNORECASE),
        ],
    ),
    (
        "Slack",
        "slack",
        [
            re.compile(r"https://[\w.-]*slack\.com/\S*huddle\S*", re.IGNORECASE),
        ],
    ),
]


def detect_platform(
    event: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    """Detect the meeting platform from event description / location.

    Returns ``(platform_display_name, source_key)`` or ``(None, None)``.
    """
    text_parts: List[str] = []
    desc = event.get("description", "")
    if desc:
        text_parts.append(desc)
    loc = event.get("location", "")
    if loc:
        text_parts.append(loc)

    combined = "\n".join(text_parts)
    if not combined:
        return None, None

    for display_name, source_key, patterns in PLATFORM_PATTERNS:
        for pat in patterns:
            if pat.search(combined):
                return display_name, source_key

    return None, None


# ---------------------------------------------------------------------------
# Description cleaning
# ---------------------------------------------------------------------------

# --- Teams boilerplate ---
# Match everything between lines of underscores (Teams meeting info block)
_TEAMS_BLOCK_RE = re.compile(
    r"_{10,}.*?_{10,}",
    re.DOTALL,
)
# Individual Teams lines that might appear outside the block
_TEAMS_LINE_PATTERNS = [
    re.compile(r"^Microsoft Teams [Mm]eeting\s*$", re.MULTILINE),
    re.compile(r"^Join:?\s*https://teams\.microsoft\.com/\S+.*$", re.MULTILINE),
    re.compile(r"^Meeting ID:\s*[\d\s]+\d\s*$", re.MULTILINE),
    re.compile(r"^Passcode:\s*\S+\s*$", re.MULTILINE),
    re.compile(r"^Dial in by phone\s*$", re.MULTILINE),
    re.compile(r"^\+[\d\s\-,#]+<tel:[^>]*>.*$", re.MULTILINE),
    re.compile(r"^Find a local number\s*<[^>]*>.*$", re.MULTILINE),
    re.compile(r"^Phone conference ID:\s*[\d\s#]+\s*$", re.MULTILINE),
    re.compile(r"^Need help\?\s*<[^>]*>.*$", re.MULTILINE),
    re.compile(r"^For organizers:.*Meeting options\s*<[^>]*>.*$", re.MULTILINE),
    re.compile(r"^Reset dial-in PIN\s*<[^>]*>.*$", re.MULTILINE),
    re.compile(r"^System reference\s*<[^>]*>.*$", re.MULTILINE),
    re.compile(r"^\|?\s*System reference\s*<[^>]*>.*$", re.MULTILINE),
    re.compile(r"^Need help\?.*https://aka\.ms/\S+.*$", re.MULTILINE),
]

# --- Zoom boilerplate ---
_ZOOM_LINE_PATTERNS = [
    re.compile(r"^Join Zoom Meeting\s*$", re.MULTILINE),
    re.compile(r"^https://[\w.-]*zoom\.us/j/\S+.*$", re.MULTILINE),
    re.compile(r"^Meeting ID:\s*[\d\s]+\d\s*$", re.MULTILINE),
    re.compile(r"^Passcode:\s*\S+\s*$", re.MULTILINE),
    re.compile(r"^Password:\s*\S+\s*$", re.MULTILINE),
    re.compile(r"^Dial by your location\s*$", re.MULTILINE),
    re.compile(r"^Find your local number:?\s*https://\S+.*$", re.MULTILINE),
    # Phone number lines: +1 234 567 8900 ... <country>
    re.compile(r"^\s*\+[\d\s\-]+.*$", re.MULTILINE),
]

# --- WebEx boilerplate ---
_WEBEX_LINE_PATTERNS = [
    re.compile(r"^Join meeting\s*$", re.MULTILINE),
    re.compile(r"^https://[\w.-]*webex\.com/\S+.*$", re.MULTILINE),
    re.compile(r"^Meeting number:?\s*[\d\s]+\d\s*$", re.MULTILINE),
    re.compile(r"^Password:\s*\S+\s*$", re.MULTILINE),
]

# Collapse excessive blank lines
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def clean_description(description: str) -> str:
    """Strip conferencing boilerplate from an event description.

    Removes join links, meeting IDs, passcodes, phone dial-in blocks,
    and footer boilerplate from Teams / Zoom / WebEx invites.
    """
    if not description:
        return ""

    text = description

    # 1. Remove Teams underscore-delimited blocks first (captures most Teams info)
    text = _TEAMS_BLOCK_RE.sub("", text)

    # 2. Remove individual Teams lines that may remain
    for pat in _TEAMS_LINE_PATTERNS:
        text = pat.sub("", text)

    # 3. Remove Zoom lines
    for pat in _ZOOM_LINE_PATTERNS:
        text = pat.sub("", text)

    # 4. Remove WebEx lines
    for pat in _WEBEX_LINE_PATTERNS:
        text = pat.sub("", text)

    # 5. Collapse 3+ consecutive newlines to 2
    text = _MULTI_BLANK_RE.sub("\n\n", text)

    return text.strip()


# ---------------------------------------------------------------------------
# Attendee formatting
# ---------------------------------------------------------------------------

def _name_from_email(email: str) -> str:
    """Derive a display name from an email address.

    ``'tim.benroeck@snowflake.com'`` -> ``'Tim Benroeck'``
    """
    local = email.split("@")[0]
    # Split on . _ - and title-case
    parts = re.split(r"[._\-]", local)
    return " ".join(p.capitalize() for p in parts if p)


def format_attendees(attendees: List[Dict[str, Any]]) -> str:
    """Build a formatted attendee list from Google Calendar attendee dicts."""
    if not attendees:
        return ""

    lines: List[str] = []
    for att in attendees:
        email = att.get("email", "")
        name = att.get("displayName", "") or _name_from_email(email)

        tags: List[str] = []
        if att.get("organizer"):
            tags.append("organizer")
        if att.get("optional"):
            tags.append("optional")
        status = att.get("responseStatus", "")
        if status and status != "needsAction":
            tags.append(status)

        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- {name} ({email}){tag_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full notes builder
# ---------------------------------------------------------------------------

def build_notes(
    event: Dict[str, Any],
    platform_name: Optional[str] = None,
    *,
    filter_conference_info: bool = True,
) -> str:
    """Compose the meeting notes text from an event.

    Parameters
    ----------
    filter_conference_info:
        If True (default), strip conferencing boilerplate (Zoom/Teams/WebEx
        join links, meeting IDs, etc.) from the description.  If False, the
        raw description is included verbatim.

    Format::

        Platform: Microsoft Teams

        Attendees (12):
        - Name (email) [tags]
        ...

        Description:
        ...body...
    """
    sections: List[str] = []

    # Platform
    if platform_name:
        sections.append(f"Platform: {platform_name}")

    # Attendees
    attendees = event.get("attendees", [])
    if attendees:
        att_text = format_attendees(attendees)
        sections.append(f"Attendees ({len(attendees)}):\n{att_text}")

    # Description
    raw_desc = event.get("description", "")
    desc = clean_description(raw_desc) if filter_conference_info else raw_desc
    if desc:
        desc = desc.strip()
    if desc:
        sections.append(f"Description:\n{desc}")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# High-level event parsing
# ---------------------------------------------------------------------------

def parse_event_for_meeting(
    event: Dict[str, Any],
    *,
    filter_conference_info: bool = True,
) -> Dict[str, Any]:
    """Parse a raw Google Calendar event into meeting-detail fields.

    Returns a dict with keys:

    - ``datetime_str``  – formatted start date/time
    - ``name``          – event summary
    - ``notes``         – composed notes (platform + attendees + description)
    - ``platform_name`` – e.g. ``"Microsoft Teams"`` or ``None``
    - ``raw``           – the original event dict
    """
    # Date/time — handle both timed and all-day events
    start = event.get("start", {})
    dt_str = start.get("dateTime", "")
    date_str = start.get("date", "")
    datetime_str = ""
    if dt_str:
        try:
            dt = datetime.datetime.fromisoformat(dt_str)
            datetime_str = dt.strftime("%m/%d/%Y %I:%M %p")
        except (ValueError, TypeError):
            datetime_str = dt_str
    elif date_str:
        # All-day event — just use the date
        try:
            d = datetime.date.fromisoformat(date_str)
            datetime_str = d.strftime("%m/%d/%Y")
        except (ValueError, TypeError):
            datetime_str = date_str

    # Summary
    name = event.get("summary", "(No title)")

    # Platform detection (informational only — not used for source selection)
    platform_name, _source_key = detect_platform(event)

    # Notes
    notes = build_notes(
        event, platform_name, filter_conference_info=filter_conference_info,
    )

    return {
        "datetime_str": datetime_str,
        "name": name,
        "notes": notes,
        "platform_name": platform_name,
        "raw": event,
    }


def format_event_label(event: Dict[str, Any]) -> str:
    """Build a short label for the event list.

    Returns e.g. ``"9:00 AM   Coke FL Databricks to Snowflake..."``
    or ``"All day   Company Holiday"``.
    """
    start = event.get("start", {})
    dt_str = start.get("dateTime", "")
    time_label = ""
    if dt_str:
        try:
            dt = datetime.datetime.fromisoformat(dt_str)
            time_label = dt.strftime("%I:%M %p").lstrip("0")
        except (ValueError, TypeError):
            time_label = dt_str
    elif is_all_day(event):
        time_label = "All day"

    summary = event.get("summary", "(No title)")
    # Truncate long summaries
    max_len = 50
    if len(summary) > max_len:
        summary = summary[: max_len - 3] + "..."

    return f"{time_label}   {summary}"
