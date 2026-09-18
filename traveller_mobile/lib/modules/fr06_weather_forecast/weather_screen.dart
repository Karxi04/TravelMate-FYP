import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../theme/app_theme.dart';

class WeatherScreen extends StatefulWidget {
  final String? initialPlace;
  final String? tripStartDate;
  final String? tripEndDate;
  final List<Map<String, dynamic>> tripActivities;

  const WeatherScreen({
    super.key,
    this.initialPlace,
    this.tripStartDate,
    this.tripEndDate,
    this.tripActivities = const [],
  });

  @override
  State<WeatherScreen> createState() => _WeatherScreenState();
}

class _WeatherScreenState extends State<WeatherScreen> {
  final place = TextEditingController(text: 'George Town');
  final api = ApiService();
  Map<String, dynamic>? weather;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    final initial = widget.initialPlace?.trim();
    if (initial != null && initial.isNotEmpty) {
      place.text = initial;
      Future.microtask(search);
    }
  }

  @override
  void dispose() {
    place.dispose();
    super.dispose();
  }

  bool get hasTripContext =>
      widget.tripStartDate != null ||
      widget.tripEndDate != null ||
      widget.tripActivities.isNotEmpty;

  Future<void> search() async {
    setState(() => busy = true);
    try {
      final geo =
          await api.get('/api/fr6/locations/search', {'q': place.text.trim()});
      final results = geo['results'] as List? ?? [];
      if (results.isEmpty) throw Exception('Location not found.');
      final first = Map<String, dynamic>.from(results.first as Map);
      final data = await api.get('/api/fr6/weather', {
        'latitude': '${first['latitude']}',
        'longitude': '${first['longitude']}'
      });
      if (!mounted) return;
      setState(
          () => weather = Map<String, dynamic>.from(data['weather'] as Map));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String adviceForDay(int code, int rain, double maxTemp, int outdoorStops) {
    final storm = code >= 95;
    final heavyRain = rain >= 70 || code == 65 || code == 82;
    final shower = rain >= 35 || [51, 53, 55, 61, 63, 80, 81].contains(code);
    final hot = maxTemp >= 33;
    if (storm || heavyRain) {
      return outdoorStops > 0
          ? 'High rain risk. Keep indoor backups for $outdoorStops outdoor stop(s).'
          : 'High rain risk. This day is better for indoor plans.';
    }
    if (shower) {
      return 'Possible showers. Outdoor stops are still usable with buffer time.';
    }
    if (hot) {
      return 'Hot day. Plan shaded breaks and water stops between activities.';
    }
    return 'Weather looks suitable for the planned route.';
  }

  @override
  Widget build(BuildContext context) {
    final current = weather?['current'] as Map?;
    final daily = weather?['daily'] as Map?;
    final times = (daily?['time'] as List?) ?? [];
    final maxes = (daily?['temperature_2m_max'] as List?) ?? [];
    final mins = (daily?['temperature_2m_min'] as List?) ?? [];
    final rain = (daily?['precipitation_probability_max'] as List?) ?? [];
    final codes = (daily?['weather_code'] as List?) ?? [];
    final outdoorStops =
        widget.tripActivities.where((a) => a['indoor'] != true).length;
    return Scaffold(
      appBar: AppBar(title: const Text('Weather Forecast')),
      body: ListView(padding: const EdgeInsets.all(18), children: [
        const SectionTitle('Destination weather',
            subtitle: 'Open-Meteo geocoding + 7-day forecast.'),
        Row(children: [
          Expanded(
              child: TextField(
                  controller: place,
                  decoration: const InputDecoration(labelText: 'Destination'))),
          const SizedBox(width: 8),
          FilledButton(
              onPressed: busy ? null : search, child: const Icon(Icons.search)),
        ]),
        const SizedBox(height: 16),
        if (current != null)
          InkCard(
              color: InkWashColors.cream,
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Current weather',
                        style: TextStyle(fontWeight: FontWeight.w800)),
                    const SizedBox(height: 8),
                    Text('${current['temperature_2m']} °C',
                        style: const TextStyle(
                            fontSize: 32, fontWeight: FontWeight.w900)),
                    Text(
                        'Humidity: ${current['relative_humidity_2m']}%  •  Wind: ${current['wind_speed_10m']} km/h'),
                  ])),
        if (hasTripContext && daily != null) ...[
          const SizedBox(height: 12),
          InkCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Trip weather planning',
                    style: TextStyle(fontWeight: FontWeight.w800)),
                const SizedBox(height: 7),
                Text(
                  '${widget.tripStartDate ?? 'Trip start'} to ${widget.tripEndDate ?? 'trip end'} • $outdoorStops outdoor stop(s)',
                  style: const TextStyle(color: InkWashColors.mutedInk),
                ),
                const SizedBox(height: 8),
                ...List.generate(times.length > 3 ? 3 : times.length, (i) {
                  final maxTemp =
                      double.tryParse('${i < maxes.length ? maxes[i] : 0}') ??
                          0;
                  final rainChance =
                      int.tryParse('${i < rain.length ? rain[i] : 0}') ?? 0;
                  final code =
                      int.tryParse('${i < codes.length ? codes[i] : 0}') ?? 0;
                  return Padding(
                    padding: const EdgeInsets.only(top: 5),
                    child: Text(
                      '${times[i]}: ${adviceForDay(code, rainChance, maxTemp, outdoorStops)}',
                      style: const TextStyle(
                          fontSize: 12, color: InkWashColors.blueGrey),
                    ),
                  );
                }),
              ],
            ),
          ),
        ],
        const SizedBox(height: 12),
        ...List.generate(
            times.length,
            (i) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: InkCard(
                    child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                      Text(times[i].toString()),
                      Text(
                          '${i < mins.length ? mins[i] : '-'}° / ${i < maxes.length ? maxes[i] : '-'}° • Rain ${i < rain.length ? rain[i] : '-'}%',
                          style: const TextStyle(fontWeight: FontWeight.w700)),
                    ])))),
      ]),
    );
  }
}
