import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_trip_actions.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/alternative_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/models/budget_model.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'fyp_evaluation_journey_test.dart' show EvaluationRecsApi;

class RecommendationWorkflowApi extends EvaluationRecsApi {
  final tripApi=WorkflowApi();
  @override Future<dynamic> get(String path,[Map<String,String>? query])=>
    path=='/api/fr5/itineraries' ? tripApi.get(path,query):super.get(path,query);
  @override Future<dynamic> post(String path,[Map<String,dynamic>? body])=>
    path.endsWith('/activities') ? tripApi.post(path,body):super.post(path,body);
}

class WorkflowApi extends ApiService {
  final requests=<Map<String,dynamic>>[];
  int tripReads=0;
  bool blockedHotel=false;
  List<Map<String,dynamic>> trips=[
    {'id':'personal','title':'Quiet Penang holiday','destinationArea':'Penang','city':'George Town','state':'Penang',
      'startDate':'2027-12-12','endDate':'2027-12-16','tripDays':5,'status':'planned','activities':[]},
    {'id':'package','title':'KL heritage package','destinationArea':'Kuala Lumpur','tripType':'package','packageTrip':true,
      'startDate':'2027-12-12','endDate':'2027-12-13','status':'planned'},
  ];
  Map<String,dynamic> get state=>{
    'ok':true,'stateVersion':'revision-one',
    'budget':{'total':1400,'limit':700,'flight':934,'hotel':300,'pendingExpenseCategories':['activities']},
    'flightComparison':{'status':'eligible','originalCabin':3,'reasons':[]},
    'hotelComparison':{'status':blockedHotel ? 'needs_review':'eligible','nextAction':'search_hotels',
      'reasons':blockedHotel ? ['The original hotel quote has expired.']:[],
      'searchCriteria':{'destination':'Penang','checkin':'2027-12-12','checkout':'2027-12-16','adults':2,
        'occupancies':[{'adults':1},{'adults':1}]}},
    'alternatives':[
      {'title':'Cheaper complete return flight','alternativeType':'flight','stateVersion':'revision-one',
       'canApply':true,'estimatedSavings':374,'currentEstimatedCost':934,'replacementEstimatedCost':560,
       'comparisonStatus':'requires_schedule_adjustment','data':{'airline':'Test Airline','cabin':{
         'cabinDowngrade':true,'originalCabin':3,'comparisonCabin':1},'outboundSegments':[{
           'departureAirportCode':'KUL','arrivalAirportCode':'PEN','departureDate':'2027-12-12',
           'departureTime':'09:00','arrivalTime':'10:00'}]}},
      {'title':'Cheaper hotel with a very long descriptive property name','alternativeType':'hotel','stateVersion':'revision-one',
       'canApply':true,'estimatedSavings':50,'currentEstimatedCost':300,'replacementEstimatedCost':250,
       'data':{'name':'Long Hotel Name','roomName':'Twin room','comparisonCriteria':{'adults':2,'roomQuantity':1,
         'checkin':'2027-12-12','checkout':'2027-12-16'}}},
    ],
  };
  @override Future<dynamic> get(String path,[Map<String,String>? query]) async {
    if(path=='/api/fr5/itineraries'){tripReads++;return {'ok':true,'items':trips};}
    return state;
  }
  @override Future<dynamic> post(String path,[Map<String,dynamic>? body]) async {
    requests.add({'path':path,'body':body});
    if(path.endsWith('/activities')) return {'ok':true,'itinerary':{'id':'personal'},'activities':[body]};
    if(path.endsWith('/preview')) return {'before':{'total':1400},'budget':{'total':1026,'overBy':326},
      'estimatedReduction':374,'dailySchedule':[{'dayNo':1,'activities':[{'activityName':'Preserved visit','scheduledStartTime':'13:00'}]}]};
    if(path.endsWith('/discover')) return {'search':{'status':'completed','requestsAttempted':2}};
    return state;
  }
}

Widget app(Widget child,{double scale=1})=>MaterialApp(theme:buildInkWashTheme(),
  builder:(context,child)=>MediaQuery(data:MediaQuery.of(context).copyWith(textScaler:TextScaler.linear(scale)),child:child!),home:child);

void main(){
  testWidgets('For You entry saves the explicitly chosen third day',(tester) async {
    final api=RecommendationWorkflowApi();
    await tester.pumpWidget(app(RecommendationScreen(api:api,initialDestination:'Penang')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Add to trip'));await tester.pump();
    await tester.tap(find.text('Add to trip'));await tester.pumpAndSettle();
    await tester.tap(find.text('Quiet Penang holiday'));await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('day-option-3')));await tester.pumpAndSettle();
    expect(api.tripApi.requests.single['body']['dayNo'],3);
    expect(api.tripApi.requests.single['body'].keys,isNot(contains('collaborativeScore')));
    expect(api.generations,0);
  });
  testWidgets('one-day personal trip skips the day picker',(tester) async {
    final api=WorkflowApi();api.trips[0].addAll({'tripDays':1,'endDate':'2027-12-12'});
    await tester.pumpWidget(app(Scaffold(body:Builder(builder:(context)=>TextButton(child:const Text('Add attraction'),
      onPressed:()=>addDestinationToTrip(context:context,api:api,destination:{'destinationId':'local_penang_hill'}))))));
    await tester.tap(find.text('Add attraction'));await tester.pumpAndSettle();
    await tester.tap(find.text('Quiet Penang holiday'));await tester.pumpAndSettle();
    expect(find.text('Select Trip Day'),findsNothing);expect(api.requests.single['body']['dayNo'],1);
  });
  testWidgets('package-only accounts get a personal-trip explanation without writes',(tester) async {
    final api=WorkflowApi();api.trips.removeAt(0);
    await tester.pumpWidget(app(Scaffold(body:Builder(builder:(context)=>TextButton(child:const Text('Add attraction'),
      onPressed:()=>addDestinationToTrip(context:context,api:api,destination:{'destinationId':'local_penang_hill'}))))));
    await tester.tap(find.text('Add attraction'));await tester.pumpAndSettle();
    expect(find.textContaining('Package itineraries are managed by the tour operator.'),findsOneWidget);
    expect(find.text('Go to Trips'),findsOneWidget);expect(api.requests,isEmpty);
  });
  testWidgets('shared attraction action chooses Day 3 and excludes package trips',(tester) async {
    final api=WorkflowApi();
    await tester.pumpWidget(app(Scaffold(body:Builder(builder:(context)=>TextButton(child:const Text('Add attraction'),
      onPressed:()=>addDestinationToTrip(context:context,api:api,destination:{'destinationId':'local_penang_hill','title':'Penang Hill'}))))));
    await tester.tap(find.text('Add attraction'));await tester.pumpAndSettle();
    expect(find.text('KL heritage package'),findsNothing);
    await tester.tap(find.text('Quiet Penang holiday'));await tester.pumpAndSettle();
    expect(api.requests, isEmpty);
    await tester.tap(find.text('Day 3 · 2027-12-14'));await tester.pumpAndSettle();
    expect(api.requests.single['body']['dayNo'],3);
    expect(api.requests.single['path'],'/api/fr5/itineraries/personal/activities');
  });
  testWidgets('cancel day selection leaves activities unchanged',(tester) async {
    final api=WorkflowApi();
    await tester.pumpWidget(app(Scaffold(body:Builder(builder:(context)=>TextButton(child:const Text('Add attraction'),
      onPressed:()=>addDestinationToTrip(context:context,api:api,destination:{'destinationId':'local_penang_hill'}))))));
    await tester.tap(find.text('Add attraction'));await tester.pumpAndSettle();
    await tester.tap(find.text('Quiet Penang holiday'));await tester.pumpAndSettle();
    Navigator.of(tester.element(find.text('Select Trip Day'))).pop();await tester.pumpAndSettle();
    expect(api.requests,isEmpty);
  });
  testWidgets('trip search filters both tabs locally and preserves status filters',(tester) async {
    final api=WorkflowApi();await tester.pumpWidget(app(TripsTab(api:api,referenceDate:DateTime(2027,12,1))));
    await tester.pumpAndSettle();final reads=api.tripReads;
    await tester.enterText(find.byType(TextField).first,'  PeNaNg   ');await tester.pumpAndSettle();
    expect(find.text('Quiet Penang holiday'),findsOneWidget);
    await tester.enterText(find.byType(TextField).first,'missing');await tester.pumpAndSettle();
    expect(find.text('No trips match your search.'),findsOneWidget);
    await tester.tap(find.byTooltip('Clear trip search'));await tester.pumpAndSettle();
    await tester.tap(find.text('Package Trips (1)'));await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first,'kuala   lumpur');await tester.pumpAndSettle();
    expect(find.text('KL heritage package'),findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('filter-expired')));await tester.pumpAndSettle();
    expect(find.text('No trips match your search.'),findsOneWidget);expect(api.tripReads,reads);
  });
  for(final width in [320.0,360.0,390.0]){
    testWidgets('comparison layout and cancel work at $width with larger text',(tester) async {
      tester.view.physicalSize=Size(width,900);tester.view.devicePixelRatio=1;
      addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
      final api=WorkflowApi();await tester.pumpWidget(app(AlternativeScreen(api:api,tripId:'personal',
        budget:BudgetModel(accommodation:300,food:100,transportation:66,activities:0,flight:934),userBudget:700),scale:1.6));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('Include lower cabin classes'),200);
      await tester.ensureVisible(find.byType(Switch).first);await tester.pump();await tester.tap(find.byType(Switch).first);await tester.pumpAndSettle();
      expect(api.requests.last['body']['cabinComparison'],'include_lower');
      await tester.scrollUntilVisible(find.text('Find cheaper flights'),120);await tester.tap(find.text('Find cheaper flights'));
      await tester.pumpAndSettle();await tester.tap(find.text('Search now'));await tester.pumpAndSettle();
      final search=api.requests.firstWhere((row)=>'${row['path']}'.endsWith('/discover'));
      expect(search['body']['cabinComparison'],'include_lower');expect(search['body']['comparisonCabin'],1);
      await tester.scrollUntilVisible(find.text('Review schedule'),180);await tester.pump();await tester.tap(find.text('Review schedule'));
      await tester.pumpAndSettle();expect(find.text('Preserved visit'),findsNothing);
      expect(find.text('13:00 Preserved visit'),findsOneWidget);
      await tester.tap(find.text('Cancel'));await tester.pumpAndSettle();
      expect(api.requests.where((row)=>'${row['path']}'.endsWith('/apply')),isEmpty);
      expect(tester.takeException(),isNull);
    });
  }
  testWidgets('hotel recovery retains trip, dates and room occupancy',(tester) async {
    final api=WorkflowApi()..blockedHotel=true;
    await tester.pumpWidget(app(AlternativeScreen(api:api,tripId:'personal',
      budget:BudgetModel(accommodation:300,food:100,transportation:66,activities:0,flight:934),userBudget:700)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Review selected stay in Hotels'),220);
    await tester.tap(find.text('Review selected stay in Hotels'));await tester.pumpAndSettle();
    final hotel=tester.widget<HotelScreen>(find.byType(HotelScreen));
    expect(hotel.targetTripId,'personal');expect(hotel.initialCheckin,'2027-12-12');expect(hotel.initialOccupancies!.length,2);
    expect(api.requests.where((row)=>'${row['path']}'.endsWith('/discover')),isEmpty);
  });
  testWidgets('methodology retains both license links in accessible details',(tester) async {
    await tester.pumpWidget(app(const Scaffold(body:RecommendationDataSources(evaluation:true))));
    await tester.tap(find.text('Recommendation data sources'));await tester.pumpAndSettle();
    expect(find.textContaining('not verified real tourists'),findsOneWidget);
    expect(find.text('GeoNames · CC BY 4.0'),findsOneWidget);
    expect(find.text('Location lookup by Open-Meteo · CC BY-NC 4.0'),findsOneWidget);
  });
}
