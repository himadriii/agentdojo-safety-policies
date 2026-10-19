"""Static tool table for the approval-reuse gate.

AgentDojo exposes no tool metadata, so P6 keeps its own: whether a tool has a side
effect, which arguments name its targets (key arguments), and which arguments are
amounts that may only go down. Everything else is free text.
"""
from dataclasses import dataclass

LIVE_SUITES = ("slack", "workspace", "travel")


@dataclass(frozen=True)
class ToolSpec:
    side_effect: bool
    key: frozenset | None = frozenset()   # None means every argument is key
    amount: frozenset = frozenset()
    probe_only: bool = False              # banking money tools: offline probes only


def _read(*key):
    return ToolSpec(side_effect=False, key=frozenset(key))


def _effect(*key, amount=(), probe_only=False):
    return ToolSpec(side_effect=True, key=frozenset(key), amount=frozenset(amount), probe_only=probe_only)


_READS = (
    # workspace
    "get_unread_emails", "get_sent_emails", "get_received_emails", "get_draft_emails", "search_emails",
    "search_contacts_by_name", "search_contacts_by_email", "get_current_day", "search_calendar_events",
    "get_day_calendar_events", "search_files_by_filename", "get_file_by_id", "list_files", "search_files",
    # travel
    "get_user_information", "get_all_hotels_in_city", "get_hotels_prices", "get_rating_reviews_for_hotels",
    "get_hotels_address", "get_all_restaurants_in_city", "get_cuisine_type_for_restaurants",
    "get_restaurants_address", "get_rating_reviews_for_restaurants",
    "get_dietary_restrictions_for_all_restaurants", "get_contact_information_for_restaurants",
    "get_price_for_restaurants", "check_restaurant_opening_hours", "get_all_car_rental_companies_in_city",
    "get_car_types_available", "get_rating_reviews_for_car_rental", "get_car_fuel_options",
    "get_car_rental_address", "get_car_price_per_day", "get_flight_information",
    # slack
    "get_channels", "read_channel_messages", "read_inbox", "get_users_in_channel",
)

TOOLS: dict[str, ToolSpec] = {name: _read() for name in _READS}
TOOLS.update({
    "get_webpage": _read("url"),
    # workspace (send_email and the calendar tools are shared with travel)
    "send_email": _effect("recipients", "cc", "bcc", "attachments"),
    "delete_email": _effect("email_id"),
    "create_calendar_event": _effect("participants"),
    "cancel_calendar_event": _effect("event_id"),
    "reschedule_calendar_event": _effect("event_id"),
    "add_calendar_event_participants": _effect("event_id", "participants"),
    "append_to_file": _effect("file_id"),
    "create_file": _effect("filename"),
    "delete_file": _effect("file_id"),
    "share_file": _effect("file_id", "email", "permission"),
    # travel
    "reserve_hotel": _effect("hotel"),
    "reserve_car_rental": _effect("company"),
    "reserve_restaurant": _effect("restaurant"),
    # slack
    "add_user_to_channel": _effect("user", "channel"),
    "send_direct_message": _effect("recipient"),
    "send_channel_message": _effect("channel"),
    "invite_user_to_slack": _effect("user", "user_email"),
    "remove_user_from_slack": _effect("user"),
    "post_webpage": _effect("url"),
    # banking, probe-only
    "send_money": _effect("recipient", amount=("amount",), probe_only=True),
    "schedule_transaction": _effect("recipient", "recurring", amount=("amount",), probe_only=True),
    "update_scheduled_transaction": _effect("id", "recipient", "recurring", amount=("amount",),
                                            probe_only=True),
})

_UNKNOWN = ToolSpec(side_effect=True, key=None)


def spec_for(tool: str) -> ToolSpec:
    return TOOLS.get(tool, _UNKNOWN)
