from __future__ import annotations

from datetime import date, datetime, timedelta

import frappe
from frappe.utils import add_days, getdate, now_datetime

CHECKIN_REMINDER_WINDOW_MINUTES = 15
CHECKOUT_REMINDER_WINDOW_MINUTES = 15


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

	for target_date in {current_date, add_days(current_date, -1)}:
		for assignment in _get_active_shift_assignments(target_date):
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
					reminder_date,
					employee_cache,
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
					reminder_date,
					employee_cache,
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


def _get_shift_window(target_date, start_time, end_time) -> tuple[datetime, datetime]:
	shift_start = datetime.combine(target_date, start_time)
	shift_end = datetime.combine(target_date, end_time)
	if shift_end <= shift_start:
		shift_end += timedelta(days=1)
	return shift_start, shift_end


def _is_within_checkin_window(now: datetime, shift_start: datetime) -> bool:
	window_start = shift_start - timedelta(minutes=CHECKIN_REMINDER_WINDOW_MINUTES)
	return window_start <= now <= shift_start


def _is_within_checkout_window(now: datetime, shift_end: datetime) -> bool:
	window_end = shift_end + timedelta(minutes=CHECKOUT_REMINDER_WINDOW_MINUTES)
	return shift_end <= now <= window_end


def _should_skip_employee(
	employee: str,
	reminder_date: date,
	employee_cache: dict[str, frappe._dict],
	holiday_list_cache: dict[tuple[str, str | None], str | None],
	holiday_cache: dict[tuple[str, str], bool],
	leave_cache: dict[tuple[str, str], bool],
) -> bool:
	employee_details = _get_employee_details(employee, employee_cache)
	if not employee_details or not employee_details.user_id:
		return True

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
	shift_type: str,
	reminder_type: str,
	reminder_date: date,
) -> bool:
	employee_details = frappe.db.get_value(
		"Employee", assignment.employee, ["user_id"], as_dict=True
	)
	if not employee_details or not employee_details.user_id:
		return False

	subject = f"{reminder_type} Reminder: {shift_type} shift on {reminder_date}"
	message = (
		f"Please remember to {reminder_type.lower()} for your {shift_type} shift scheduled on "
		f"{reminder_date}."
	)

	if _notification_exists(employee_details.user_id, assignment.name, subject):
		return False

	notification = frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": employee_details.user_id,
			"type": "Alert",
			"document_type": "Shift Assignment",
			"document_name": assignment.name,
			"subject": subject,
			"email_content": message,
		}
	)
	notification.insert(ignore_permissions=True)
	return True


def _notification_exists(user_id: str, assignment_name: str, subject: str) -> bool:
	return bool(
		frappe.db.exists(
			"Notification Log",
			{
				"for_user": user_id,
				"document_type": "Shift Assignment",
				"document_name": assignment_name,
				"subject": subject,
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
