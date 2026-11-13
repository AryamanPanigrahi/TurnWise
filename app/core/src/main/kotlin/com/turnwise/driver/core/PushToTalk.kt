package com.turnwise.driver.core

/**
 * Push-to-talk and the speaker, as one state machine.
 *
 * Rules it enforces:
 * - Audio is captured only between press and release (CLAUDE.md rule 4: never
 *   stream continuously). A clip is cut at [maxClipMs] because Sarvam's REST
 *   speech-to-text accepts at most 30 s.
 * - A wrong-way alert always wins: it interrupts a recording or an answer and is
 *   spoken immediately (rule 2). Questions asked during an alert are ignored.
 * - Presses shorter than [minClipMs] are treated as accidental and discarded,
 *   so no audio (and no money) is sent for them.
 *
 * Time is passed in (`nowMs`) so the logic is testable without a clock.
 */
class PushToTalk(
    private val minClipMs: Long = 300,
    private val maxClipMs: Long = 25_000,
) {
    sealed interface State {
        data object Idle : State
        data class Recording(val startedMs: Long) : State
        data object WaitingForAnswer : State
        data object SpeakingAnswer : State
        data object SpeakingAlert : State
    }

    /** What the Android layer must do after an input. */
    sealed interface Action {
        data object None : Action
        data object StartMic : Action
        data object StopMicAndDiscard : Action
        data class StopMicAndSend(val clipMs: Long) : Action
        data object PlayAnswer : Action
        /** Stop whatever is playing or recording, then play the alert. */
        data object InterruptAndPlayAlert : Action
    }

    var state: State = State.Idle
        private set

    fun press(nowMs: Long): Action = when (state) {
        State.Idle, State.SpeakingAnswer -> { state = State.Recording(nowMs); Action.StartMic }
        else -> Action.None
    }

    fun release(nowMs: Long): Action {
        val s = state as? State.Recording ?: return Action.None
        val clip = nowMs - s.startedMs
        return if (clip < minClipMs) {
            state = State.Idle; Action.StopMicAndDiscard
        } else {
            state = State.WaitingForAnswer; Action.StopMicAndSend(minOf(clip, maxClipMs))
        }
    }

    /** Call regularly while recording; cuts the clip at the limit. */
    fun tick(nowMs: Long): Action {
        val s = state as? State.Recording ?: return Action.None
        return if (nowMs - s.startedMs >= maxClipMs) {
            state = State.WaitingForAnswer; Action.StopMicAndSend(maxClipMs)
        } else Action.None
    }

    fun answerReady(): Action = when (state) {
        State.WaitingForAnswer -> { state = State.SpeakingAnswer; Action.PlayAnswer }
        else -> Action.None // the driver moved on, or an alert is playing
    }

    fun answerFailed(): Action {
        if (state == State.WaitingForAnswer) state = State.Idle
        return Action.None
    }

    fun alert(): Action { state = State.SpeakingAlert; return Action.InterruptAndPlayAlert }

    fun playbackFinished(): Action {
        if (state == State.SpeakingAnswer || state == State.SpeakingAlert) state = State.Idle
        return Action.None
    }
}
