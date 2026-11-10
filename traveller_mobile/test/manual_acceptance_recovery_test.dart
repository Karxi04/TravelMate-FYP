import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/home/home_tab.dart';
import 'package:travelmate_traveller/core/utils/package_departures.dart';
import 'package:travelmate_traveller/core/utils/recommendation_taxonomy.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/modules/traveller_notifications/notification_center.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_history_screen.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'core_personalization_notifications_test.dart' show RecsApi, NoticesApi;

class SharedGenerationApi extends RecsApi {
  SharedGenerationApi() {
    minimum=45;
    pool.clear();
    pool.add({'destinationId':'penang-street-art','title':'Penang Street Art',
      'discoveryEligible':true,'finalScore':61,'personalSuitabilityScore':80,'scoringVersion':'recovery_v3'});
  }
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    if(path=='/api/fr4/settings') return {'minimumMatchScore':minimum,'scoreBasis':'personal_v2'};
    if(path=='/api/fr1/me') return {'profile':{'name':'Isolated Traveller'}};
    if(path=='/api/fr2/preferences') return {'preferences':{'interests':['Photography','Food'],'travelPersonality':'Planner','travelPace':'Moderate'}};
    return super.get(path,query);
  }
}

class ContextNoticesApi extends NoticesApi {
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    if(path=='/api/fr9/payments') return {'ok':true,'items':[{'id':'order1','orderReference':'order1','paymentStatus':'paid','productTitle':'Butterworth Full Day','amount':100,'currency':'MYR'}]};
    return super.get(path,query);
  }
}

class OldBackendApi extends SharedGenerationApi {
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    if(path=='/api/fr4/recommendations') return {'recommendationGenerationId':'old','recommendations':[{'title':'Penang Street Art','finalScore':61}]};
    return super.get(path,query);
  }
}

void main() {
  test('bounded English Malay and Mandarin metadata is real evidence',() {
    for(final text in ['Photogenic murals','Street photography','Scenic viewpoints','街頭攝影','观景台']) {
      expect(RecommendationTaxonomy.candidateConcepts({'title':text}),contains('photography'));
    }
    for(final text in ['小贩中心','美食街','茶室','Medan selera','Kopitiam']) {
      expect(RecommendationTaxonomy.candidateConcepts({'title':text}),contains('food'));
    }
    expect(RecommendationTaxonomy.candidateConcepts({'title':'Popular tourist attraction'}),isNot(contains('photography')));
    for (final text in ['没有壁画','附近有壁画','沒有小販中心','附近有小贩中心']) {
      final concepts=RecommendationTaxonomy.candidateConcepts({'title':'Visitor centre','description':text});
      expect(concepts.intersection({'photography','food'}),isEmpty);
    }
  });

  test('Malaysia midnight invalidates dates without silently changing selection',() {
    final before=DateTime.utc(2026,11,8,15,59);
    final after=DateTime.utc(2026,11,8,16);
    expect(packageDepartureAvailable('2026-11-08',now:before),isTrue);
    expect(packageDepartureAvailable('2026-11-08',now:after),isFalse);
    expect(packageDepartureAvailable('2026-11-09',now:after),isTrue);
    expect(packageDepartureAvailable('2026-02-30',now:after),isFalse);
    expect(packageDepartureError(['2026-11-07'],'2026-11-07',now:after),contains('Checkout is unavailable'));
    expect(packageDepartureError(['2026-11-10'],'2026-11-07',now:after),isNotNull);
    expect(packageDepartureError([],null,now:after),isNull);
  });

  test('old backend cannot turn unavailable personal scoring into false zero',() {
    expect(()=>validateRecommendationResponse({'recommendations':[]},'personal_v2'),throwsStateError);
    expect(()=>validateRecommendationResponse({'recommendations':[],'pagination':{'scoreBasis':'personal_v2','personalEvidenceCount':0}},'personal_v2'),returnsNormally);
  });

  testWidgets('Home See all shares generation and scope without applying old settings',(tester) async {
    tester.view.physicalSize=const Size(1000,2600); tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final api=SharedGenerationApi();
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:HomeTab(api:api)));
    await tester.pumpAndSettle();
    final before=api.reads.length;
    await tester.ensureVisible(find.text('See all').first);
    await tester.tap(find.text('See all').first); await tester.pumpAndSettle();
    expect(find.byType(RecommendationScreen),findsOneWidget);
    expect(api.reads.last['generationId'],'generation_0');
    expect(api.reads.last['destinationArea'],'Penang');
    expect(api.reads.last['discoveryMode'],recommendationDiscoveryMode);
    expect(find.text('Penang Street Art'),findsOneWidget);
    api.minimum=85;
    await tester.pageBack(); await tester.pumpAndSettle();
    expect(api.reads.length,greaterThan(before+1));
    expect(api.reads.last['minimumMatchScore'],isNull);
    expect(find.text('Penang Street Art'),findsOneWidget);
  });

  testWidgets('old backend displays compatibility error instead of no matches',(tester) async {
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:RecommendationScreen(api:OldBackendApi(),initialDestination:'Penang')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Something went wrong. Please try again.'),300,scrollable:find.byType(Scrollable).first);
    expect(find.text('Something went wrong. Please try again.'),findsOneWidget);
    expect(find.text('No places meet this minimum match'),findsNothing);
  });

  testWidgets('payment context remains visible and tap preserves exact order navigation',(tester) async {
    final api=ContextNoticesApi();
    api.items.single['sourceLabel']='Butterworth Full Day · Order order1';
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:NotificationCenterScreen(api:api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('Butterworth Full Day · Order order1'),findsOneWidget);
    await tester.tap(find.text('Payment status updated'));await tester.pumpAndSettle();
    final screen=tester.widget<PaymentHistoryScreen>(find.byType(PaymentHistoryScreen));
    expect(screen.focusOrderId,'order1');
    expect(find.text('Payment Details'),findsOneWidget);
    expect(find.text('order1'),findsOneWidget);
    expect(api.updates.single['path'],'/api/traveller/notifications/event1');
    expect(api.updates.single['read'],isTrue);
  });
}
