from datetime import datetime, timezone
import tzlocal
import pytz


def local_to_utc(user_time):
    # parse it into a datetime object
    if isinstance(user_time, str):
        user_time = datetime.strptime(user_time, '%H:%M:%S')

    # Get local time zone
    local_tz = tzlocal.get_localzone()
    local_time = user_time.replace(tzinfo=local_tz)

    # Convert to UTC
    utc_time = local_time.astimezone(timezone.utc)
    return utc_time.strftime('%H:%M:%S')


def utc_to_local(utc_time):
    if not isinstance(utc_time, datetime):
        # parse it into a datetime object
        utc_time = datetime.strptime(utc_time, '%H:%M:%S')

    # Set the timezone to UTC
    utc_time = utc_time.replace(tzinfo=timezone.utc)

    # Get the local timezone
    user_tz = tzlocal.get_localzone()

    # Convert to local timezone
    local_time = utc_time.astimezone(user_tz)
    return local_time.strftime('%H:%M:%S')


def time_format_locale(time):
    local_tz = tzlocal.get_localzone()

    if isinstance(time, str):
        hrs, mins, sec = map(int, time.split(':'))
        time_obj = datetime.now().replace(hour=hrs, minute=mins, second=sec, microsecond=0)
        time_obj = time_obj.replace(tzinfo=local_tz)
    else:
        hrs, mins, sec = time.hour, time.minute, time.second
        time_obj = time.replace(tzinfo=local_tz)
        hrs, mins, sec = time_obj.hour, time_obj.minute, time_obj.second

    period = "AM" if hrs < 12 else "PM"

    hrs = hrs % 12 if hrs != 0 else 12

    get_tz = time_obj.strftime('%Z')

    return f"{hrs:01d}:{mins:02d}:{sec:02d} {period} {get_tz}" if hrs > 10 else f"{hrs:02d}:{mins:02d}:{sec:02d} {period} {get_tz}"


def find_timezone(timestamp):
    offset = timestamp.strftime('%z')
    offset_hrs = int(offset[0:3])
    offset_mins = int(offset[0] + offset[3:])

    us_timezones = [tz for tz in pytz.all_timezones if tz.startswith("US/")]
    for tz in us_timezones:
        timezone = pytz.timezone(tz)
        current_time = datetime.now(timezone)

        if current_time.utcoffset().total_seconds() == (offset_hrs * 3600 + offset_mins * 60):
            return tz

    return None


def convert_locale(time, timezone_str):
    timezone = pytz.timezone(timezone_str)

    current_date = datetime.now().date()

    # Parse the time into a datetime object if it's a string
    if isinstance(time, str):
        time_obj = datetime.strptime(time, '%H:%M:%S')
        # Combine the current date with the parsed time
        time_obj = datetime.combine(current_date, time_obj.time())
    else:
        time_obj = time

    time_obj = time_obj.replace(tzinfo=pytz.utc).astimezone(timezone)

    period = "AM" if time_obj.hour < 12 else "PM"
    hrs = time_obj.hour % 12 if time_obj.hour %12 != 0 else 12
    get_tz = time_obj.strftime('%Z')

    return f"{hrs:01d}:{time_obj.minute:02d} {period} {get_tz}" if hrs > 10 else f"{hrs:02d}:{time_obj.minute:02d} {period} {get_tz}"


def date_format(date):
    if isinstance(date, str):
        try:
            date = datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise ValueError("String input must be in the 'YYYY-MM-DD' format")

    elif not isinstance(date, datetime):
        raise ValueError(
            "Input must be a string in 'YYYY-MM-DD' format or a datetime object")

    return date.strftime('%m-%d-%Y')
