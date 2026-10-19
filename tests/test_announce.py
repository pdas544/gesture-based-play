from __future__ import annotations

from gesture_media_control.announce import NullAnnouncer, SpeechDispatcherAnnouncer


class FakeProcess:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0


def _announcer(popen, which=lambda name: f"/usr/bin/{name}"):
    return SpeechDispatcherAnnouncer(which=which, popen=popen)


def test_say_starts_spd_say() -> None:
    calls = []

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    announcer = _announcer(popen)
    announcer.say("Hi, how can I help")

    assert calls[0][0] == ["/usr/bin/spd-say", "-w", "Hi, how can I help"]
    assert announcer.is_speaking is True


def test_speaking_is_false_after_process_exits() -> None:
    process = FakeProcess()
    announcer = _announcer(lambda *_a, **_k: process)

    announcer.say("hello")
    process.returncode = 0

    assert announcer.is_speaking is False


def test_does_not_start_second_utterance_while_speaking() -> None:
    calls = []

    def popen(args, **kwargs):
        calls.append(args)
        return FakeProcess()

    announcer = _announcer(popen)
    announcer.say("one")
    announcer.say("two")

    assert len(calls) == 1


def test_missing_binary_is_a_noop(caplog) -> None:
    calls = []
    announcer = _announcer(lambda *a, **k: calls.append(a), which=lambda _name: None)

    announcer.say("hello")
    announcer.say("again")

    assert calls == []
    assert announcer.is_speaking is False


def test_blank_text_is_ignored() -> None:
    calls = []
    announcer = _announcer(lambda *a, **k: calls.append(a))

    announcer.say("   ")

    assert calls == []


def test_stop_terminates_running_speech() -> None:
    process = FakeProcess()
    announcer = _announcer(lambda *_a, **_k: process)

    announcer.say("hello")
    announcer.stop()

    assert process.terminated is True
    assert announcer.is_speaking is False


def test_null_announcer() -> None:
    announcer = NullAnnouncer()
    announcer.say("hello")
    announcer.stop()
    assert announcer.is_speaking is False
