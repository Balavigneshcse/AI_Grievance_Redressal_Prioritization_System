"""Refusals the app can show in the user's language.

Every error a citizen or an officer can meet is raised as ApiError(status, code, **params). The response keeps
FastAPI's shape, with the English message in "detail" for API clients and the test suite, and adds the stable
code and its parameters:

    {"detail": "Please keep the complaint to 5000 characters or fewer", "code": "complaint_too_long", "params": {"max": 5000}}

The app shows apiErrors.<code> from frontend/src/i18n/{en,ta,hi}.json filled with the parameters, and the
English message for a code it does not know. Request validation (422) keeps FastAPI's own list in "detail".
"""
from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

# Code -> English message, filled from the parameters. Each code needs apiErrors.<code> in the three language
# files, using only these parameters (tests/test_api_e2e.py checks both).
MESSAGES: dict[str, str] = {
    # session and sign-in
    "not_authenticated": "Not authenticated",
    "token_invalid": "Invalid or expired token",
    "session_ended": "Session no longer valid",
    "account_disabled": "Account disabled",
    "account_not_verified": "Account not verified",
    "role_not_allowed": "Not allowed for this role",
    "not_found": "Not found",
    "too_many_attempts": "Too many attempts. Please wait a minute and try again.",
    "login_failed": "Incorrect email or password",
    # registration, codes, profile and staff accounts
    "code_invalid": "Incorrect or expired code. Check it, or request a new one.",
    "code_attempts_exceeded": "Too many attempts. Request a new code.",
    "name_invalid": "Please enter your full name",
    "aadhaar_invalid": "Enter the last 4 digits of your Aadhaar number",
    "mobile_invalid": "Mobile number must be 10 digits starting with 6-9",
    "email_invalid": "Invalid email address",
    "password_weak": "Password needs {missing}",  # missing: rule ids; the message names them in words (security.check_password)
    "email_taken": "An account with this email already exists",
    "mobile_taken": "An account with this mobile number already exists",
    "dept_admins_only": "A district admin can only create department admins",
    "district_required": "Choose a Tamil Nadu district",
    "district_unknown": "Unknown district",
    "department_required": "Choose a department",
    "department_unknown": "Unknown department",
    "staff_not_found": "Staff account not found",
    "super_admin_locked": "Another super admin cannot be changed",
    "outside_district": "Outside your district",
    "cannot_disable_self": "You cannot disable your own account",
    # complaints and attachments
    "complaint_too_short": "Please describe the problem in at least a few words",
    "complaint_too_long": "Please keep the complaint to {max} characters or fewer",
    "location_incomplete": "Send both lat and lng, or neither",
    "location_out_of_range": "lat must be between -90 and 90 and lng between -180 and 180",
    "profile_incomplete": "Add your name and the last 4 digits of your Aadhaar number to your account first",
    "too_many_files": "Attach at most {max} photos or videos at a time",
    "file_type_refused": "{name}: only JPEG, PNG or WebP photos and WebM, MP4 or MOV videos are accepted",
    "file_too_large": "{name} is larger than {max} MB ({kind} limit)",
    "complaint_not_found": "Complaint not found",
    "media_not_found": "Media not found",
    "not_your_complaint": "Not your complaint",
    "outside_scope": "Outside your district or department",
    # reply, feedback and me-too support
    "reply_not_owner": "Only the complainant can reply",
    "complaint_closed": "This complaint is closed",
    "reply_empty": "Write a reply or attach a photo or video",
    "feedback_not_owner": "Only the complainant can give feedback",
    "feedback_not_resolved": "Feedback is possible once the complaint is resolved",
    "feedback_window_closed": "The feedback window has closed",
    "rating_required": "Give a rating from 1 to 5, or reopen the complaint",
    "support_citizens_only": "Only citizens can support a complaint",
    "support_own_complaint": "You filed this complaint",
    "complaint_not_open": "This complaint is no longer open",
    "support_location_required": "Send your location: only complaints near you can be supported",
    "support_too_far": "Only complaints within {km:g} km of you can be supported",
    # review decisions and office attachments
    "not_your_department": "Not your department",
    "decision_not_allowed": "Cannot {action} from status {status}",  # the message spells request_info as "request info"
    "already_routed": "Already routed: the department admin starts the work",
    "reassign_target_missing": "reassign needs a department or an urgency",
    "merge_target_missing": "merge needs merged_into",
    "merge_target_not_found": "Target complaint not found",
    "merge_target_duplicate": "Target is itself a duplicate; merge into the original",
    "attachment_required": "Attach at least one photo or video",
    # rules (super admin)
    "rules_invalid": "Invalid rules: {reason}",
}


class ApiError(HTTPException):
    """An HTTP error with a stable code and its parameters. The English message comes from MESSAGES unless
    one is given (when it spells a parameter differently from the value the app receives)."""

    def __init__(self, status_code: int, code: str, *, message: str | None = None, headers: dict[str, str] | None = None, **params):
        super().__init__(status_code, message or MESSAGES[code].format(**params), headers=headers)
        self.code = code
        self.params = params


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "code": exc.code, "params": exc.params}, status_code=exc.status_code, headers=exc.headers)
