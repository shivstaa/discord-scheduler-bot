from datetime import datetime, timezone
import tzlocal


def local_to_utc(user_time):
    user_time = datetime.strptime(user_time, '%H:%M:%S')

    # Get local time
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
