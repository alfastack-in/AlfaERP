from __future__ import annotations

from datetime import date, datetime, time, timedelta

import frappe
from frappe.utils import add_days, formatdate, getdate, now_datetime

DEFAULT_REMINDER_WINDOW_MINUTES = 15
CHECKIN_REMINDER_WINDOW_MINUTES = DEFAULT_REMINDER_WINDOW_MINUTES
CHECKOUT_REMINDER_WINDOW_MINUTES = DEFAULT_REMINDER_WINDOW_MINUTES
REMINDER_ACTIONS = {
	"Check-In": "check in",
	"Check-Out": "check out",
}
SUBJECT_TEMPLATE = "{reminder_type} Reminder: {shift_type} shift on {date}"
MESSAGE_TEMPLATE = "Please remember to {action} for your {shift_type} shift scheduled on {date}."


def send_shift_reminders() -> None:
	now = now_datetime()
	current_date = getdate(now)

	shift_type_cache: dict[str, frappe._dict] = {}
	employee_cache: dict[str, frappe._dict] = {}
	holiday_list_cache: dict[tuple[str, str | None], str | None] = {}
	holiday_cache: dict[tuple[str, str], bool] = {}
	leave_cache: dict[tuple[str, str], bool] = {}
	shift_field = _get_employee_checkin_shift_field()
	logger = frappe.logger("shift_reminders")

	# Include the previous day to catch overnight shifts that end after midnight.
	for target_date in [current_date, add_days(current_date, -1)]:
		for assignment in _get_active_shift_assignments(target_date):
			employee_details = _get_employee_details(assignment.employee, employee_cache)
			if not employee_details or not employee_details.user_id:
				continue

			shift_type = assignment.shift_type
			shift_times = shift_type_cache.get(shift_type)
			if not shift_times:
				shift_times = frappe.db.get_value(
					"Shift Type", shift_type, ["start_time", "end_time"], as_dict=True
				)
				shift_type_cache[shift_type] = shift_times

			if not shift_times or not shift_times.start_time or not shift_times.end_time:
				continue

			shift_start, shift_end = _get_shift_window(
				target_date, shift_times.start_time, shift_times.end_time
			)

			if _is_within_checkin_window(now, shift_start):
				reminder_date = shift_start.date()
				if _should_skip_employee(
					assignment.employee,
					employee_details,
					reminder_date,
					holiday_list_cache,
					holiday_cache,
					leave_cache,
				):
					continue
				if _has_employee_log(
					assignment.employee,
					shift_start,
					shift_end,
					"IN",
					shift_type,
					shift_field,
				):
					continue
				if _send_reminder(
					assignment,
					employee_details.user_id,
					shift_type,
					"Check-In",
					reminder_date,
				):
					logger.info(
						"Sent check-in reminder",
						employee=assignment.employee,
						shift_assignment=assignment.name,
						shift_type=shift_type,
						date=str(reminder_date),
					)

			if _is_within_checkout_window(now, shift_end):
				reminder_date = shift_end.date()
				if _should_skip_employee(
					assignment.employee,
					employee_details,
					reminder_date,
					holiday_list_cache,
					holiday_cache,
					leave_cache,
				):
					continue
				if _has_employee_log(
					assignment.employee,
					shift_start,
					shift_end,
					"OUT",
					shift_type,
					shift_field,
				):
					continue
				if _send_reminder(
					assignment,
					employee_details.user_id,
					shift_type,
					"Check-Out",
					reminder_date,
				):
					logger.info(
						"Sent check-out reminder",
						employee=assignment.employee,
						shift_assignment=assignment.name,
						shift_type=shift_type,
						date=str(reminder_date),
					)


def _get_active_shift_assignments(target_date: date) -> list[frappe._dict]:
	return frappe.get_all(
		"Shift Assignment",
		filters=[
			["start_date", "<=", target_date],
			["docstatus", "=", 1],
		],
		or_filters=[
			["end_date", ">=", target_date],
			["end_date", "is", "not set"],
		],
		fields=["name", "employee", "shift_type"],
	)


def _get_shift_window(
	target_date: date,
	start_time: time,
	end_time: time,
) -> tuple[datetime, datetime]:
	shift_start = datetime.combine(target_date, start_time)
	shift_end = datetime.combine(target_date, end_time)
	if shift_end <= shift_start:
		# Overnight shift ends on the following day.
		shift_end += timedelta(days=1)
	return shift_start, shift_end


def _is_within_checkin_window(now: datetime, shift_start: datetime) -> bool:
	window_minutes = _get_window_minutes(
		"shift_checkin_reminder_minutes",
		CHECKIN_REMINDER_WINDOW_MINUTES,
	)
	window_start = shift_start - timedelta(minutes=window_minutes)
	return window_start <= now < shift_start


def _is_within_checkout_window(now: datetime, shift_end: datetime) -> bool:
	window_minutes = _get_window_minutes(
		"shift_checkout_reminder_minutes",
		CHECKOUT_REMINDER_WINDOW_MINUTES,
	)
	window_end = shift_end + timedelta(minutes=window_minutes)
	return shift_end <= now < window_end


def _should_skip_employee(
	employee: str,
	employee_details: frappe._dict,
	reminder_date: date,
	holiday_list_cache: dict[tuple[str, str | None], str | None],
	holiday_cache: dict[tuple[str, str], bool],
	leave_cache: dict[tuple[str, str], bool],
) -> bool:
	if _is_employee_on_holiday(
		employee_details,
		reminder_date,
		holiday_list_cache,
		holiday_cache,
	):
		return True

	if _is_employee_on_leave(employee, reminder_date, leave_cache):
		return True

	return False


def _get_employee_details(
	employee: str,
	employee_cache: dict[str, frappe._dict],
) -> frappe._dict | None:
	if employee in employee_cache:
		return employee_cache[employee]
	employee_details = frappe.db.get_value(
		"Employee",
		employee,
		["user_id", "holiday_list", "company"],
		as_dict=True,
	)
	employee_cache[employee] = employee_details
	return employee_details


def _is_employee_on_holiday(
	employee_details: frappe._dict,
	reminder_date: date,
	holiday_list_cache: dict[tuple[str, str | None], str | None],
	holiday_cache: dict[tuple[str, str], bool],
) -> bool:
	holiday_list = employee_details.holiday_list
	if not holiday_list:
		holiday_list = holiday_list_cache.get((employee_details.company, None))
		if holiday_list is None and employee_details.company:
			holiday_list = frappe.db.get_value(
				"Company", employee_details.company, "default_holiday_list"
			)
			holiday_list_cache[(employee_details.company, None)] = holiday_list

	if not holiday_list:
		return False

	cache_key = (holiday_list, str(reminder_date))
	if cache_key not in holiday_cache:
		holiday_cache[cache_key] = bool(
			frappe.db.exists(
				"Holiday",
				{
					"parent": holiday_list,
					"holiday_date": reminder_date,
				},
			)
		)
	return holiday_cache[cache_key]


def _is_employee_on_leave(
	employee: str,
	reminder_date: date,
	leave_cache: dict[tuple[str, str], bool],
) -> bool:
	cache_key = (employee, str(reminder_date))
	if cache_key not in leave_cache:
		leave_cache[cache_key] = bool(
			frappe.db.exists(
				"Leave Application",
				{
					"employee": employee,
					"status": "Approved",
					"docstatus": 1,
					"from_date": ["<=", reminder_date],
					"to_date": [">=", reminder_date],
				},
			)
		)
	return leave_cache[cache_key]


def _has_employee_log(
	employee: str,
	shift_start: datetime,
	shift_end: datetime,
	log_type: str,
	shift_type: str,
	shift_field: str | None,
) -> bool:
	filters = {
		"employee": employee,
		"log_type": log_type,
		"time": ["between", [shift_start, shift_end]],
	}
	if shift_field:
		filters[shift_field] = shift_type
	return bool(frappe.db.exists("Employee Checkin", filters))


def _send_reminder(
	assignment: frappe._dict,
	user_id: str,
	shift_type: str,
	reminder_type: str,
	reminder_date: date,
) -> bool:
	formatted_date = formatdate(reminder_date)
	subject = SUBJECT_TEMPLATE.format(
		reminder_type=reminder_type,
		shift_type=shift_type,
		date=formatted_date,
	)
	action = REMINDER_ACTIONS.get(reminder_type, reminder_type.lower())
	message = MESSAGE_TEMPLATE.format(
		action=action,
		shift_type=shift_type,
		date=formatted_date,
	)

	if _notification_exists(user_id, assignment.name, reminder_type, reminder_date):
		return False

	notification = frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": user_id,
			"type": "Alert",
			"document_type": "Shift Assignment",
			"document_name": assignment.name,
			"subject": subject,
			"email_content": message,
		}
	)
	try:
		notification.insert(ignore_permissions=True)
	except Exception:
		frappe.logger("shift_reminders").exception(
			"Failed to insert shift reminder notification",
			user_id=user_id,
			shift_assignment=assignment.name,
			reminder_type=reminder_type,
		)
		return False

	return True


def _notification_exists(
	user_id: str,
	assignment_name: str,
	reminder_type: str,
	reminder_date: date,
) -> bool:
	subject_prefix = f"{reminder_type} Reminder:"
	start_of_day = datetime.combine(reminder_date, time.min)
	end_of_day = datetime.combine(reminder_date, time.max)
	return bool(
		frappe.db.exists(
			"Notification Log",
			{
				"for_user": user_id,
				"document_type": "Shift Assignment",
				"document_name": assignment_name,
				"subject": ["like", f"{subject_prefix}%"],
				"creation": ["between", [start_of_day, end_of_day]],
			},
		)
	)


def _get_employee_checkin_shift_field() -> str | None:
	meta = frappe.get_meta("Employee Checkin")
	if meta.has_field("shift_type"):
		return "shift_type"
	if meta.has_field("shift"):
		return "shift"
	return None


def _get_window_minutes(config_key: str, default_minutes: int) -> int:
	raw_value = frappe.conf.get(config_key, default_minutes)
	try:
		return int(raw_value)
	except (TypeError, ValueError):
		frappe.logger("shift_reminders").warning(
			"Invalid shift reminder window setting, using default",
			config_key=config_key,
			value=raw_value,
			default=default_minutes,
		)
		return default_minutes
