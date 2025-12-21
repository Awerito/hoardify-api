from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .spotify import poll_current_playback, poll_recently_played, sync_artists


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        poll_current_playback,
        IntervalTrigger(seconds=30),
        id="poll_current_playback",
        replace_existing=True,
    )

    scheduler.add_job(
        poll_recently_played,
        CronTrigger.from_crontab("0 * * * *"),  # Every hour at :00
        id="poll_recently_played",
        replace_existing=True,
    )

    scheduler.add_job(
        sync_artists,
        CronTrigger.from_crontab("0 6,18 * * *"),  # 6 AM and 6 PM
        id="sync_artists",
        replace_existing=True,
    )
