package com.example.travelmate_traveller

import org.junit.Assert.*
import org.junit.Test

class TripReminderRulesTest {
    @Test fun reminderIsDueInItsWindowOnly() {
        assertFalse(TripReminderRules.due(99,100,200,false,true))
        assertTrue(TripReminderRules.due(100,100,200,false,true))
        assertTrue(TripReminderRules.due(150,100,200,false,true))
        assertFalse(TripReminderRules.due(200,100,200,false,true))
    }
    @Test fun repeatedDeliveryAndDeniedPermissionNeverAlert() {
        assertFalse(TripReminderRules.due(150,100,200,true,true))
        assertFalse(TripReminderRules.due(150,100,200,false,false))
    }
}
