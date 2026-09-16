"""The service owns the connection, so it owns the lock.

shared.get_email_service() releases its factory lock before the caller sends, so a
settings change that closes the old service can land inside another thread's send.
Guarding send and quit together here is what makes that safe.
"""

import threading

from src.services.email_service import EmailService


def _service(tmp_path) -> EmailService:
    cv = tmp_path / "cv.docx"
    cv.write_bytes(b"cv")
    return EmailService(
        host="smtp.example.com", port=587, user="u@example.com", password="p",
        sender_name="Ada", cv_path=str(cv),
    )


def test_quit_waits_for_a_send_in_flight(tmp_path):
    service = _service(tmp_path)
    sending = threading.Event()
    release = threading.Event()

    class FakeClient:
        def noop(self):
            return 250, b""

        def send_message(self, msg):
            sending.set()
            release.wait(5)
            return {}

        def quit(self):
            pass

    service._client = FakeClient()

    sender = threading.Thread(
        target=service.send_application_email, args=("to@example.com", "s", "b")
    )
    sender.start()
    assert sending.wait(5)

    closer = threading.Thread(target=service.quit)
    closer.start()
    closer.join(0.5)
    assert closer.is_alive(), "quit tore the connection down inside the send"

    release.set()
    sender.join(5)
    closer.join(5)
    assert not closer.is_alive()
    assert service._client is None
