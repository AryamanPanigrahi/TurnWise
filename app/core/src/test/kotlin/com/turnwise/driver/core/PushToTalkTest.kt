package com.turnwise.driver.core

import com.turnwise.driver.core.PushToTalk.Action
import com.turnwise.driver.core.PushToTalk.State
import kotlin.test.Test
import kotlin.test.assertEquals

class PushToTalkTest {
    @Test fun normalQuestion() {
        val p = PushToTalk()
        assertEquals(Action.StartMic, p.press(0))
        assertEquals(Action.StopMicAndSend(2000), p.release(2000))
        assertEquals(Action.PlayAnswer, p.answerReady())
        p.playbackFinished()
        assertEquals(State.Idle, p.state)
    }

    @Test fun accidentalTapSendsNothing() {
        val p = PushToTalk(minClipMs = 300)
        p.press(0)
        assertEquals(Action.StopMicAndDiscard, p.release(100))
        assertEquals(State.Idle, p.state)
    }

    @Test fun longClipIsCutAtLimit() {
        val p = PushToTalk(maxClipMs = 25_000)
        p.press(0)
        assertEquals(Action.None, p.tick(24_000))
        assertEquals(Action.StopMicAndSend(25_000), p.tick(25_000))
        assertEquals(Action.None, p.release(26_000))
    }

    @Test fun alertInterruptsRecordingAndAnswer() {
        val p = PushToTalk()
        p.press(0)
        assertEquals(Action.InterruptAndPlayAlert, p.alert())
        assertEquals(Action.None, p.release(2000))   // the question is dropped
        assertEquals(Action.None, p.press(2500))     // can't ask during the alert
        assertEquals(Action.None, p.answerReady())   // a late answer isn't played
        p.playbackFinished()
        assertEquals(State.Idle, p.state)
    }

    @Test fun driverCanInterruptAnAnswerWithANewQuestion() {
        val p = PushToTalk()
        p.press(0); p.release(1000); p.answerReady()
        assertEquals(Action.StartMic, p.press(1500))
    }

    @Test fun failedAnswerReturnsToIdle() {
        val p = PushToTalk()
        p.press(0); p.release(1000); p.answerFailed()
        assertEquals(State.Idle, p.state)
    }
}
