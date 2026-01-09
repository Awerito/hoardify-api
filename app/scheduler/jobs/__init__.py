from datetime import datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .spotify import (
    poll_current_playback,
    poll_recently_played,
    ensure_poller_alive,
    set_scheduler,
)


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    # Set scheduler reference for self-scheduling
    set_scheduler(scheduler)

    # First poll runs immediately, then self-schedules
    scheduler.add_job(
        poll_current_playback,
        trigger="date",
        run_date=datetime.now() + timedelta(seconds=1),
        id="poll_current_playback",
        replace_existing=True,
        misfire_grace_time=60,
    )

    scheduler.add_job(
        poll_recently_played,
        CronTrigger.from_crontab("0 * * * *"),  # Every hour at :00
        id="poll_recently_played",
        replace_existing=True,
    )

    # Watchdog: check every 30 seconds if poller is alive
    scheduler.add_job(
        ensure_poller_alive,
        IntervalTrigger(seconds=30),
        id="poller_watchdog",
        replace_existing=True,
    )

