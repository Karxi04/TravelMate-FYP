import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_taxonomy.dart';
import 'package:travelmate_traveller/core/utils/constraint_itinerary_planner.dart';

Map<String, dynamic> place(String id, String title, String category, double lat, double lng) => {
  'activityId': id, 'destinationId': id, 'activityName': title, 'title': title,
  'category': category, 'gps_coordinates': {'latitude':lat,'longitude':lng},
  'openingHours':'08:00-21:00','recommendedDurationMinutes':75,
};

void main() {
  test('tourism eligibility uses provider function and keeps legitimate visitor venues', () {
    for(final type in ['gas_station','residential area','Housing development','government office', 'bank', 'car_repair', 'real_estate_agency']) {
      expect(isTourismPlanningCandidate({'title':'Local venue','type':type}), isFalse);
    }
    for(final type in ['Restaurant','Botanical garden','Museum']) {
      expect(isTourismPlanningCandidate({'title':'Neighbourhood venue','type':type}), isTrue);
    }
  });
  test('standalone chooses the feasible nature and shopping cluster', () {
    final rows = [
      for(var i=0;i<5;i++) place('hike$i','Hiking trail $i','Nature',2.05+i*.001,102.57),
      place('beach','Beach','Nature',1.49,103.75),
      place('garden','Botanic Garden','Nature',1.492,103.75),
      place('mall','Shopping Mall','Shopping',1.493,103.75),
    ];
    final plan = planConstraintAwareItinerary({
      'activities':rows,'interests':['Nature','Shopping'],'geographyPlanningPolicy':localDaysPolicy,
      'startDate':'2030-12-12','endDate':'2030-12-12','travelMode':'own_vehicle','travelPace':'Packed',
    });
    expect((plan['activities'] as List).cast<Map>().map((row)=>row['activityId']).toSet(),
      {'beach','garden','mall'});
  });
}
