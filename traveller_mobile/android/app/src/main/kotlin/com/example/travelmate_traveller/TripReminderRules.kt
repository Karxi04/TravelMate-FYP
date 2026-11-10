package com.example.travelmate_traveller

internal object TripReminderRules {
    fun due(now: Long, trigger: Long, expires: Long, delivered: Boolean, allowed: Boolean) =
        now >= trigger && now < expires && !delivered && allowed
}
