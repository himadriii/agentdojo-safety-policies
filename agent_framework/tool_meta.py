"""Static, semantic labels for tools. Label by what a tool DOES, never by which tools injection tasks use."""
from dataclasses import asdict, dataclass

READ_PREFIXES = ("get_", "search_", "list_", "read_", "find_", "lookup_", "fetch_", "check_")


@dataclass(frozen=True)
class ToolMeta:
    category: str
    read_only: bool
    external_side_effect: bool      # reaches someone other than the user (or moves money / publishes)
    irreversible: bool              # cannot be undone by another normal tool call
    untrusted_output: bool          # result contains third-party-authored text (injection surface)
    target_args: tuple = ()         # args naming who/what is affected; should trace back to the user's request
    sensitive_output: bool = False  # result is private data (exfiltration risk if a later write sends it out)
    known: bool = True              # False = fallback guess for a tool missing from the table


def _read(cat, untrusted=True, sensitive=False):
    return ToolMeta(cat, True, False, False, untrusted, (), sensitive)


def _write(cat, targets, external=True, irreversible=True):
    return ToolMeta(cat, False, external, irreversible, False, tuple(targets))


TOOL_META = {
    # ================= workspace (also shared by travel) =================
    # ---- email ----
    "get_unread_emails": _read("email"),
    "get_sent_emails": _read("email"),
    "get_received_emails": _read("email"),
    "get_draft_emails": _read("email"),
    "search_emails": _read("email"),
    "search_contacts_by_name": _read("email", untrusted=False),
    "search_contacts_by_email": _read("email", untrusted=False),
    "send_email": _write("email", ("recipients", "cc", "bcc", "attachments")),
    "delete_email": _write("email", ("email_id",), external=False),
    # ---- calendar ----
    "get_current_day": _read("calendar", untrusted=False),
    "search_calendar_events": _read("calendar"),
    "get_day_calendar_events": _read("calendar"),
    "create_calendar_event": _write("calendar", ("participants",), irreversible=False),   # invites people
    "cancel_calendar_event": _write("calendar", ("event_id",)),                          # notifies participants
    "reschedule_calendar_event": _write("calendar", ("event_id",), irreversible=False),
    "add_calendar_event_participants": _write("calendar", ("event_id", "participants"), irreversible=False),
    # ---- cloud drive ----
    "list_files": _read("drive"),
    "get_file_by_id": _read("drive"),
    "search_files": _read("drive"),
    "search_files_by_filename": _read("drive"),
    "create_file": _write("drive", ("filename",), external=False, irreversible=False),
    "append_to_file": _write("drive", ("file_id",), external=False, irreversible=False),
    "delete_file": _write("drive", ("file_id",), external=False),
    "share_file": _write("drive", ("file_id", "email")),                                  # disclosure can't be undone

    # ================= travel =================
    # listings and prices: third-party data, but no free-text reviews
    "get_all_hotels_in_city": _read("travel"),
    "get_all_restaurants_in_city": _read("travel"),
    "get_all_car_rental_companies_in_city": _read("travel"),
    "get_hotels_prices": _read("travel"),
    "get_hotels_address": _read("travel"),
    "get_restaurants_address": _read("travel"),
    "get_price_for_restaurants": _read("travel"),
    "get_cuisine_type_for_restaurants": _read("travel"),
    "get_dietary_restrictions_for_all_restaurants": _read("travel"),
    "get_contact_information_for_restaurants": _read("travel"),
    "check_restaurant_opening_hours": _read("travel"),
    "get_car_rental_address": _read("travel"),
    "get_car_types_available": _read("travel"),
    "get_car_fuel_options": _read("travel"),
    "get_car_price_per_day": _read("travel"),
    "get_flight_information": _read("travel"),
    # reviews are free text written by third parties
    "get_rating_reviews_for_hotels": _read("travel"),
    "get_rating_reviews_for_restaurants": _read("travel"),
    "get_rating_reviews_for_car_rental": _read("travel"),
    "get_user_information": _read("travel", untrusted=False, sensitive=True),
    # bookings: no cancel tool exists, so they cannot be undone
    "reserve_hotel": _write("travel", ("hotel",)),
    "reserve_restaurant": _write("travel", ("restaurant",)),
    "reserve_car_rental": _write("travel", ("company",)),

    # ================= banking =================
    "get_balance": _read("banking", untrusted=False, sensitive=True),
    "get_iban": _read("banking", untrusted=False, sensitive=True),
    "get_user_info": _read("banking", untrusted=False, sensitive=True),
    "get_most_recent_transactions": _read("banking", sensitive=True),     # subjects are third-party text
    "get_scheduled_transactions": _read("banking", sensitive=True),
    "read_file": _read("banking"),                                         # file contents are third-party text
    "send_money": _write("banking", ("recipient", "amount")),
    "schedule_transaction": _write("banking", ("recipient", "amount"), irreversible=False),
    "update_scheduled_transaction": _write("banking", ("id", "recipient", "amount"), irreversible=False),
    "update_password": _write("banking", ("password",), external=False),   # old credential is lost
    "update_user_info": _write("banking", ("street", "city"), external=False, irreversible=False),

    # ================= slack =================
    "get_channels": _read("slack", untrusted=False),
    "get_users_in_channel": _read("slack", untrusted=False),
    "read_channel_messages": _read("slack"),
    "read_inbox": _read("slack"),
    "get_webpage": _read("slack"),                 # read-only, but its URL can leak data (see notes)
    "send_direct_message": _write("slack", ("recipient",)),
    "send_channel_message": _write("slack", ("channel",)),
    "post_webpage": _write("slack", ("url",)),
    "add_user_to_channel": _write("slack", ("user", "channel")),            # no tool removes a user from a channel
    "invite_user_to_slack": _write("slack", ("user", "user_email"), irreversible=False),
    "remove_user_from_slack": _write("slack", ("user",)),                    # judgement call: can be re-invited, state is lost
}


def get_tool_meta(name: str) -> dict:
    """Plain dict for policies. Unknown tools get a conservative fallback with known=False."""
    meta = TOOL_META.get(name)
    if meta is not None:
        return asdict(meta)
    if name.startswith(READ_PREFIXES):
        guess = ToolMeta("unknown", True, False, False, True, (), True, known=False)
    else:
        guess = ToolMeta("unknown", False, True, True, False, (), False, known=False)
    return asdict(guess)
