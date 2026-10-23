package io.github.upgradedev.mercury.wallboard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CockpitLoadStateTest {
    private val target = "https://example.test:8443/cockpit/?agent=1"

    @Test
    fun loadingDoesNotRouteKeysUntilTheDocumentFinishes() {
        val state = CockpitLoadState(target)
        assertFalse(state.pageLoaded)
        assertTrue(state.finishLoad())
        assertTrue(state.pageLoaded)
        state.beginLoad()
        assertFalse(state.pageLoaded)
        assertFalse(state.offline)
    }

    @Test
    fun aBrokenSubresourceDoesNotReplaceTheWorkingCockpit() {
        val state = CockpitLoadState(target)
        state.finishLoad()
        assertFalse(state.fail(false))
        assertFalse(state.fail(false, 503))
        assertTrue(state.pageLoaded)
        assertFalse(state.offline)
    }

    @Test
    fun networkFailureCannotBeOverwrittenByALateFinishedCallback() {
        val state = CockpitLoadState(target)
        state.finishLoad()
        assertTrue(state.fail(true))
        assertFalse(state.finishLoad())
        assertFalse(state.pageLoaded)
        assertTrue(state.offline)
    }

    @Test
    fun onlyFailedMainDocumentHttpResponsesTriggerRecovery() {
        for (code in listOf(200, 302, 399)) {
            val state = CockpitLoadState(target)
            state.finishLoad()
            assertFalse(state.fail(true, code))
            assertTrue(state.pageLoaded)
        }
        for (code in listOf(400, 404, 503)) {
            val state = CockpitLoadState(target)
            assertTrue(state.fail(true, code))
            assertTrue(state.offline)
            assertFalse(state.pageLoaded)
        }
    }

    @Test
    fun retryUsesTheSameResolvedUrlAndCanReturnToTheCockpit() {
        val state = CockpitLoadState(target)
        state.fail(true, 503)
        assertEquals(target, state.retry())
        assertFalse(state.pageLoaded)
        assertFalse(state.offline)
        assertTrue(state.finishLoad())
        assertTrue(state.pageLoaded)
    }

    @Test
    fun aFailedRetryRemainsRecoverableWithoutChangingTheTarget() {
        val state = CockpitLoadState(target)
        repeat(2) {
            assertTrue(state.fail(true))
            assertFalse(state.finishLoad())
            assertEquals(target, state.retry())
        }
    }
}
