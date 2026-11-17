"""Generate and deliver Word notes after the upstream transcription pipeline."""
from email.message import EmailMessage
from pathlib import Path
import smtplib
import time

from cloud_notes.lecture_status import eligible
from cloud_notes.store import Store
from cloud_notes.word import create_word

ROOT = Path(__file__).resolve().parents[1]


def send_attachment(emailer, row, path):
    message = EmailMessage()
    message["Subject"] = f"课程笔记 | {row['course_title']} | {row['sub_title']}"
    message["From"] = emailer.sender
    message["To"] = emailer.receiver
    message.set_content("本节课程笔记见 Word 附件。")
    message.add_attachment(
        path.read_bytes(),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )
    with smtplib.SMTP_SSL(emailer.host, emailer.port, timeout=35) as server:
        server.login(emailer.sender, emailer.password)
        rejected = server.send_message(message)
        if rejected:
            raise RuntimeError("附件邮件未被接收")


class LectureBatch:
    """Leave time for the active lecture and save each result before its email."""

    def __init__(self, store, *, clock=time.monotonic):
        self.store = store
        self.clock = clock
        self.deadline = clock() + 4 * 3600 + 45 * 60
        self.max_lectures = 12
        self.queue_size = 0
        self.processed = 0
        self.attempted_mail = set()
        self.failures = 0
        self.emailer = None

    def can_start(self):
        return self.processed < self.max_lectures and self.clock() < self.deadline

    def can_prefetch(self):
        return self.processed + 1 < self.max_lectures and self.clock() < self.deadline

    def save(self, db, phase):
        self.store.save(db, {
            "phase": phase,
            "total": self.queue_size,
            "checked": self.processed,
            "current": f"本轮已检查 {self.processed}/{self.queue_size} 个待处理课次",
        })

    def record_lecture(self, db, item):
        self.processed += 1
        if item:
            self.deliver(db, item)
        else:
            self.save(db, "正在处理课次")

    def deliver(self, db, row):
        self.attempted_mail.add(str(row["sub_id"]))
        try:
            path = create_word(row, self.store.root)
        except Exception as error:
            self.failures += 1
            print("Word 生成失败："+type(error).__name__)
            self.save(db, "已保存转写，部分 Word 待重试")
            return

        self.save(db, "已保存本节 Word")
        if not self.emailer:
            return
        try:
            send_attachment(self.emailer, row, path)
        except Exception as error:
            self.failures += 1
            print("附件邮件发送失败："+type(error).__name__)
            return
        db.mark_emailed_batch([row["sub_id"]])
        self.save(db, "已发送本节 Word 附件")

    def finish(self, db):
        deliveries = 0
        for raw in db.get_unsent_lectures():
            if deliveries >= self.max_lectures or self.clock() >= self.deadline:
                break
            row = dict(raw)
            if str(row["sub_id"]) not in self.attempted_mail and eligible(row):
                self.deliver(db, row)
                deliveries += 1
        remaining = any(eligible(dict(row)) for row in db.get_unsent_lectures())
        if self.failures:
            phase = "本轮进度已保存，部分 Word 或邮件待重试"
        elif self.processed < self.queue_size or remaining:
            phase = "本批进度已保存，下次继续"
        else:
            phase = "课程检查完成"
        self.save(db, phase)



def main():
    from main import run
    from src.data.database import Database

    store = Store(ROOT)
    store.restore()
    try:
        run(LectureBatch(store))
    except Exception as error:
        with_checkpoint(store, Database, "任务未完成", type(error).__name__)
        raise SystemExit(1) from None


def with_checkpoint(store, database_class, phase, error_type=None):
    db = database_class()
    detail = {"phase": phase}
    if error_type:
        print(f"{phase}：{error_type}")
        detail["error_type"] = error_type
    store.save(db, detail)


if __name__ == "__main__":
    main()

