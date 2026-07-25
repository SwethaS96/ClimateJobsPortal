import schedule
import time


def run(job_func):
    schedule.every().day.at("00:00").do(job_func)
    while True:
        schedule.run_pending()
        time.sleep(1)
