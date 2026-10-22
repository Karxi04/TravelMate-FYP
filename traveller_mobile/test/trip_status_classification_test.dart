import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_status_helper.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';

void main() {
  group('TripStatusHelper - Date Parsing and Timezone', () {
    test('parses standard calendar dates without UTC day shifts', () {
      final date = TripStatusHelper.parseCalendarDate('2026-10-22');
      expect(date, isNotNull);
      expect(date!.year, 2026);
      expect(date.month, 10);
      expect(date.day, 22);
    });

    test('validates leap year and rejects invalid leap dates', () {
      // 2028 is a leap year
      expect(TripStatusHelper.parseCalendarDate('2028-02-29'), isNotNull);
      // 2026 & 2027 are not leap years
      expect(TripStatusHelper.parseCalendarDate('2026-02-29'), isNull);
      expect(TripStatusHelper.parseCalendarDate('2027-02-29'), isNull);
      // Day 31 in 30-day months
      expect(TripStatusHelper.parseCalendarDate('2026-04-31'), isNull);
      expect(TripStatusHelper.parseCalendarDate('2026-06-31'), isNull);
      expect(TripStatusHelper.parseCalendarDate('2026-09-31'), isNull);
      expect(TripStatusHelper.parseCalendarDate('2026-11-31'), isNull);
    });

    test('rejects malformed and out of range date strings', () {
      expect(TripStatusHelper.parseCalendarDate(''), isNull);
      expect(TripStatusHelper.parseCalendarDate(null), isNull);
      expect(TripStatusHelper.parseCalendarDate('invalid-date'), isNull);
      expect(TripStatusHelper.parseCalendarDate('2026-13-01'), isNull);
      expect(TripStatusHelper.parseCalendarDate('2026-00-10'), isNull);
      expect(TripStatusHelper.parseCalendarDate('2026-10-35'), isNull);
    });

    test('calculates Malaysia calendar date correctly regardless of phone UTC offset', () {
      // 2026-10-21 20:00:00 UTC is 2026-10-22 04:00:00 in Malaysia (+8)
      final utcNight = DateTime.utc(2026, 10, 21, 20, 0, 0);
      final myToday = TripStatusHelper.getMalaysiaToday(utcNight);
      expect(myToday, DateTime(2026, 10, 22));

      // 2026-10-22 15:59:59 UTC is 2026-10-22 23:59:59 in Malaysia (+8)
      final utcEvening = DateTime.utc(2026, 10, 22, 15, 59, 59);
      final myToday2 = TripStatusHelper.getMalaysiaToday(utcEvening);
      expect(myToday2, DateTime(2026, 10, 22));

      // 2026-10-22 16:00:01 UTC is 2026-10-23 00:00:01 in Malaysia (+8)
      final utcNextDay = DateTime.utc(2026, 10, 22, 16, 0, 1);
      final myToday3 = TripStatusHelper.getMalaysiaToday(utcNextDay);
      expect(myToday3, DateTime(2026, 10, 23));
    });
  });

  group('TripStatusHelper - Date Boundary and Error Cases (Prompt Section 10)', () {
    final refToday = DateTime(2026, 10, 22);

    test('1. Trip starts tomorrow -> Planned', () {
      final trip = {'startDate': '2026-10-23', 'endDate': '2026-10-25'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.planned);
    });

    test('2. Trip starts today -> Ongoing', () {
      final trip = {'startDate': '2026-10-22', 'endDate': '2026-10-26'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.ongoing);
    });

    test('3. Trip started yesterday and continues -> Ongoing', () {
      final trip = {'startDate': '2026-10-21', 'endDate': '2026-10-24'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.ongoing);
    });

    test('4. Trip ends today -> Ongoing (end date is inclusive)', () {
      final trip = {'startDate': '2026-10-18', 'endDate': '2026-10-22'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.ongoing);
    });

    test('5. Trip ended yesterday -> Expired', () {
      final trip = {'startDate': '2026-10-15', 'endDate': '2026-10-21'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.expired);
    });

    test('6. Single-day Trip today -> Ongoing', () {
      final trip = {'startDate': '2026-10-22', 'endDate': '2026-10-22'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.ongoing);
    });

    test('7. Single-day Trip yesterday -> Expired', () {
      final trip = {'startDate': '2026-10-21', 'endDate': '2026-10-21'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.expired);
    });

    test('8. Single-day Trip tomorrow -> Planned', () {
      final trip = {'startDate': '2026-10-23', 'endDate': '2026-10-23'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.planned);
    });

    test('9. Multi-day Trip spanning a month boundary', () {
      final upcoming = {'startDate': '2026-10-30', 'endDate': '2026-11-04'};
      expect(TripStatusHelper.resolveStatus(upcoming, referenceDate: refToday), TripTemporalStatus.planned);

      final active = {'startDate': '2026-10-20', 'endDate': '2026-11-02'};
      expect(TripStatusHelper.resolveStatus(active, referenceDate: refToday), TripTemporalStatus.ongoing);

      final past = {'startDate': '2026-09-28', 'endDate': '2026-10-03'};
      expect(TripStatusHelper.resolveStatus(past, referenceDate: refToday), TripTemporalStatus.expired);
    });

    test('10. Multi-day Trip spanning a year boundary', () {
      final trip = {'startDate': '2026-12-29', 'endDate': '2027-01-04'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.planned);
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: DateTime(2027, 1, 1)), TripTemporalStatus.ongoing);
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: DateTime(2027, 1, 5)), TripTemporalStatus.expired);
    });

    test('11. Leap year travel dates handled properly', () {
      final leapTrip = {'startDate': '2028-02-28', 'endDate': '2028-03-01'};
      expect(TripStatusHelper.resolveStatus(leapTrip, referenceDate: DateTime(2028, 2, 29)), TripTemporalStatus.ongoing);

      final invalidLeapTrip = {'startDate': '2027-02-29', 'endDate': '2027-03-02'};
      expect(TripStatusHelper.resolveStatus(invalidLeapTrip, referenceDate: refToday), isNull);
    });

    test('12. Invalid startDate -> returns null', () {
      final trip = {'startDate': 'not-a-date', 'endDate': '2026-10-25'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), isNull);
    });

    test('13. Invalid endDate -> returns null (unless tripDays fallback is valid)', () {
      final trip = {'startDate': '2026-10-20', 'endDate': 'corrupt-date'};
      // Without tripDays, cannot determine end
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), isNull);
    });

    test('14. Missing startDate -> returns null', () {
      final trip = {'endDate': '2026-10-25'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), isNull);
    });

    test('15. Missing endDate with valid tripDays fallback', () {
      final tripWithDays = {'startDate': '2026-10-20', 'tripDays': 4}; // ends 2026-10-23
      expect(TripStatusHelper.resolveStatus(tripWithDays, referenceDate: refToday), TripTemporalStatus.ongoing);

      final tripWithoutDays = {'startDate': '2026-10-20'};
      expect(TripStatusHelper.resolveStatus(tripWithoutDays, referenceDate: refToday), isNull);
    });

    test('16. endDate earlier than startDate -> strictly disqualified (returns null)', () {
      final trip = {'startDate': '2026-10-25', 'endDate': '2026-10-20'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), isNull);
    });

    test('17. Legacy Trip with stale nested dailySchedule uses authoritative top-level dates', () {
      final historicalTrip = {
        'id': 'MBdcQ3NF1onYkCXivEaJ',
        'title': 'My Personalised Penang Trip',
        'startDate': '2026-10-31',
        'endDate': '2026-11-03',
        'tripDays': 3,
        'dailySchedule': [
          {'dayNo': 1, 'dayDate': '2026-09-17'},
          {'dayNo': 2, 'dayDate': '2026-09-18'},
          {'dayNo': 3, 'dayDate': '2026-09-19'},
        ],
      };
      // On 22 October 2026, top-level dates (31 Oct - 3 Nov) mean Planned
      expect(TripStatusHelper.resolveStatus(historicalTrip, referenceDate: refToday), TripTemporalStatus.planned);

      // On 1 November 2026, Ongoing
      expect(TripStatusHelper.resolveStatus(historicalTrip, referenceDate: DateTime(2026, 11, 1)), TripTemporalStatus.ongoing);

      // On 4 November 2026, Expired
      expect(TripStatusHelper.resolveStatus(historicalTrip, referenceDate: DateTime(2026, 11, 4)), TripTemporalStatus.expired);
    });

    test('18. Trip with valid dates but empty activities is classified normally', () {
      final trip = {'startDate': '2026-10-25', 'endDate': '2026-10-28', 'activities': []};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.planned);
    });

    test('19. Trip with valid budget and booking references is classified normally', () {
      final trip = {
        'startDate': '2026-10-20',
        'endDate': '2026-10-25',
        'budgetEstimate': {'total': 1500.0},
        'bookingReference': 'order_hotel_123',
      };
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: refToday), TripTemporalStatus.ongoing);
    });

    test('20. Phone timezone change does not shift calendar day', () {
      // Regardless of local time, referenceDate uses calendar date
      final trip = {'startDate': '2026-10-22', 'endDate': '2026-10-22'};
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: DateTime(2026, 10, 22, 23, 59)), TripTemporalStatus.ongoing);
      expect(TripStatusHelper.resolveStatus(trip, referenceDate: DateTime(2026, 10, 22, 0, 1)), TripTemporalStatus.ongoing);
    });

    test('21. Midnight calculation returns positive duration', () {
      final duration = TripStatusHelper.durationUntilMidnight();
      expect(duration.inSeconds, greaterThan(0));
      expect(duration.inHours, lessThanOrEqualTo(24));
    });

    test('22. Filtering and category transitions with sortAndFilterTrips', () {
      final trips = [
        {'id': 't_exp', 'startDate': '2026-10-10', 'endDate': '2026-10-12'},
        {'id': 't_ong', 'startDate': '2026-10-20', 'endDate': '2026-10-25'},
        {'id': 't_pln', 'startDate': '2026-10-26', 'endDate': '2026-10-28'},
        {'id': 't_inv', 'startDate': 'bad-date', 'endDate': 'bad-date'},
      ];

      // All filter: Ongoing first, then Planned, then Expired, then Invalid
      final all = TripStatusHelper.sortAndFilterTrips(trips, filter: TripFilter.all, referenceDate: refToday);
      expect(all.map((t) => t['id']).toList(), ['t_ong', 't_pln', 't_exp', 't_inv']);

      // Ongoing filter: only t_ong
      final ongoing = TripStatusHelper.sortAndFilterTrips(trips, filter: TripFilter.ongoing, referenceDate: refToday);
      expect(ongoing.map((t) => t['id']).toList(), ['t_ong']);

      // Planned filter: only t_pln
      final planned = TripStatusHelper.sortAndFilterTrips(trips, filter: TripFilter.planned, referenceDate: refToday);
      expect(planned.map((t) => t['id']).toList(), ['t_pln']);

      // Expired filter: only t_exp
      final expired = TripStatusHelper.sortAndFilterTrips(trips, filter: TripFilter.expired, referenceDate: refToday);
      expect(expired.map((t) => t['id']).toList(), ['t_exp']);
    });

    test('24. Zero Trips and zero matching Trips handle gracefully', () {
      final empty = TripStatusHelper.sortAndFilterTrips([], filter: TripFilter.planned, referenceDate: refToday);
      expect(empty, isEmpty);

      final onlyExpired = [
        {'id': 't1', 'startDate': '2026-10-10', 'endDate': '2026-10-12'},
      ];
      final noOngoing = TripStatusHelper.sortAndFilterTrips(onlyExpired, filter: TripFilter.ongoing, referenceDate: refToday);
      expect(noOngoing, isEmpty);
    });
  });

  group('TripTemporalStatus presentation metadata', () {
    test('Planned presentation uses calm blue and schedule icon', () {
      const status = TripTemporalStatus.planned;
      expect(status.label, 'Planned');
      expect(status.tone, AppStatusTone.info);
      expect(status.icon, isNotNull);
    });

    test('Ongoing presentation uses green and explore icon', () {
      const status = TripTemporalStatus.ongoing;
      expect(status.label, 'Ongoing');
      expect(status.tone, AppStatusTone.success);
      expect(status.icon, isNotNull);
    });

    test('Expired presentation uses neutral tone and history icon', () {
      const status = TripTemporalStatus.expired;
      expect(status.label, 'Expired');
      expect(status.tone, AppStatusTone.neutral);
      expect(status.icon, isNotNull);
    });
  });
}
