"""Generate and deliver Word notes after the upstream transcription pipeline."""
from email.message import EmailMessage
from pathlib import Path
import smtplib

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


def publish(store, emailer, db, new_items):
    rows = {str(row["sub_id"]): dict(row) for row in db.get_unsent_lectures() if eligible(row)}
    rows.update((str(row["sub_id"]), row) for row in new_items)
    generated = []
    failed = False
    for row in rows.values():
        try:
            generated.append((row, create_word(row, store.root)))
        except Exception as error:
            failed = True
            print("Word 生成失败："+type(error).__name__)
    store.save(db, {"phase": "Word 已保存，正在处理附件邮件"})
    if emailer:
        for row, path in generated:
            try:
                send_attachment(emailer, row, path)
            except Exception as error:
                failed = True
                print("附件邮件发送失败："+type(error).__name__)
                continue
            db.mark_emailed_batch([row["sub_id"]])
            store.save(db, {"phase": "正在处理附件邮件"})
    if failed:
        raise RuntimeError("部分 Word 或附件邮件待重试")


def main():
    from main import run
    from src.data.database import Database

    store = Store(ROOT)
    store.restore()
    try:
        run(lambda emailer, db, items: publish(store, emailer, db, items))
    except Exception as error:
        with_checkpoint(store, Database, "任务未完成", type(error).__name__)
        raise SystemExit(1) from None
    with_checkpoint(store, Database, "课程检查完成")


def with_checkpoint(store, database_class, phase, error_type=None):
    db = database_class()
    detail = {"phase": phase}
    if error_type:
        print(f"{phase}：{error_type}")
        detail["error_type"] = error_type
    store.save(db, detail)


if __name__ == "__main__":
    main()

