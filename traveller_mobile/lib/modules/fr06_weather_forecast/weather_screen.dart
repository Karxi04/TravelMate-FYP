import 'dart:async';
import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class WeatherScreen extends StatefulWidget {
  final String? initialPlace;
  final String? tripStartDate;
  final String? tripEndDate;
  final List<Map<String, dynamic>> tripActivities;
  final ApiService? api;
  const WeatherScreen({super.key, this.initialPlace, this.tripStartDate,
    this.tripEndDate, this.tripActivities = const [], this.api});
  @override
  State<WeatherScreen> createState() => _WeatherScreenState();
}

class _WeatherScreenState extends State<WeatherScreen> {
  late final TextEditingController place;
  final focus = FocusNode();
  late final ApiService api;
  Map<String, dynamic>? selectedLocation;
  Map<String, dynamic>? weather;
  String? error;
  bool busy = false;
  int version = 0;
  int suggestionVersion = 0;
  Timer? suggestionTimer;
  Completer<Iterable<Map<String, dynamic>>>? pendingSuggestions;
  String locationName(Map<String, dynamic> item) => [item['name'], item['admin1'], item['country']]
      .where((v) => v != null && v.toString().isNotEmpty).join(', ');
  @override
  void initState() {
    super.initState(); api = widget.api ?? ApiService();
    place = TextEditingController(text: widget.initialPlace ?? '');
    place.addListener(() {
      version++;
      if (selectedLocation != null && place.text != locationName(selectedLocation!)) {
        setState(() { selectedLocation = null; weather = null; });
      }
    });
  }
  @override
  void dispose() {
    version++; suggestionVersion++; suggestionTimer?.cancel();
    if (pendingSuggestions?.isCompleted == false) pendingSuggestions!.complete(const []);
    place.dispose(); focus.dispose(); super.dispose();
  }

  Future<Iterable<Map<String, dynamic>>> locations(TextEditingValue value) {
    suggestionTimer?.cancel();
    if (pendingSuggestions?.isCompleted == false) pendingSuggestions!.complete(const []);
    final pending = Completer<Iterable<Map<String, dynamic>>>();
    pendingSuggestions = pending;
    final request = ++suggestionVersion;
    if (value.text.trim().length < 2) { pending.complete(const []); return pending.future; }
    suggestionTimer = Timer(const Duration(milliseconds: 300), () async {
      try {
        final data = await api.get('/api/fr6/locations/search', {'q': value.text.trim()});
        if (!mounted || request != suggestionVersion) { if (!pending.isCompleted) pending.complete(const []); return; }
        final items = (data['results'] as List? ?? []).whereType<Map>()
          .where((v) => v['latitude'] is num && v['longitude'] is num)
          .map((v) => Map<String, dynamic>.from(v)).toList();
        if (!pending.isCompleted) pending.complete(items);
      } catch (_) {
        if (mounted && request == suggestionVersion) setState(() => error = 'Location search is unavailable. Try typing again.');
        if (!pending.isCompleted) pending.complete(const []);
      }
    });
    return pending.future;
  }

  Future<void> search() async {
    if (selectedLocation == null || place.text != locationName(selectedLocation!)) {
      setState(() { error = 'Search for and select a location from the suggestions.'; weather = null; });
      return;
    }
    final request = ++version;
    setState(() { busy = true; error = null; weather = null; });
    try {
      final data = await api.get('/api/fr6/weather', {
        'latitude': '${selectedLocation!['latitude']}', 'longitude': '${selectedLocation!['longitude']}'
      });
      if (!mounted || request != version) return;
      setState(() => weather = Map<String, dynamic>.from(data['weather'] as Map));
    } catch (e) {
      if (mounted && request == version) setState(() => error = userFacingApiError(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String conditions(dynamic code) {
    final c = int.tryParse('$code');
    if (c == 0) return 'Clear sky';
    if (c != null && c <= 3 && c >= 1) return 'Partly cloudy or overcast';
    if ([45,48].contains(c)) return 'Fog';
    if ([51,53,55,56,57].contains(c)) return 'Drizzle';
    if ([61,63,65,66,67,80,81,82].contains(c)) return 'Rain or showers';
    if ([71,73,75,77,85,86].contains(c)) return 'Snow';
    if ([95,96,99].contains(c)) return 'Thunderstorm';
    return 'Conditions unavailable';
  }
  dynamic dailyValue(Map daily, String key, int index) {
    final values = daily[key];
    return values is List && index < values.length ? values[index] : null;
  }
  bool inTrip(String day) =>
      (widget.tripStartDate == null || day.compareTo(widget.tripStartDate!.split('T').first) >= 0) &&
      (widget.tripEndDate == null || day.compareTo(widget.tripEndDate!.split('T').first) <= 0);
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
    final current = weather?['current'] is Map ? weather!['current'] as Map : const {};
    final units = weather?['current_units'] is Map ? weather!['current_units'] as Map : const {};
    final daily = weather?['daily'] is Map ? weather!['daily'] as Map : const {};
    final days = daily['time'] is List ? daily['time'] as List : const [];
    final hasTrip = widget.tripStartDate != null || widget.tripEndDate != null;
    final outdoorStops = widget.tripActivities.where((a) => a['indoor'] != true).length;
    return Scaffold(appBar: AppBar(title: const Text('Weather Forecast')),
      body: ListView(padding: const EdgeInsets.all(18), children: [
        const SectionTitle('Destination weather', subtitle: 'Search and select a location. Forecast data: Open-Meteo.'),
        LayoutBuilder(builder: (context, constraints) => RawAutocomplete<Map<String, dynamic>>(
          textEditingController: place, focusNode: focus, displayStringForOption: locationName,
          optionsBuilder: locations,
          onSelected: (location) { setState(() { selectedLocation = location; weather = null; error = null; }); },
          fieldViewBuilder: (_, controller, node, submit) => TextField(controller: controller, focusNode: node,
            decoration: const InputDecoration(labelText: 'Destination', hintText: 'Search city or place'), onSubmitted: (_) => search()),
          optionsViewBuilder: (_, select, options) => Align(alignment: Alignment.topLeft,
            child: Material(elevation: 4, child: SizedBox(width: constraints.maxWidth, height: 210,
              child: ListView(padding: EdgeInsets.zero, children: options.map((item) => ListTile(
                title: Text(locationName(item)), onTap: () => select(item))).toList())))),
        )),
        const SizedBox(height: 12),
        FilledButton(onPressed: busy ? null : search, child: Text(busy ? 'Loading forecast...' : 'Show weather')),
        if (error != null) AppErrorState(message: error!, onRetry: search),
        if (current.isNotEmpty) InkCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(locationName(selectedLocation!)),
          Text(conditions(current['weather_code']), style: Theme.of(context).textTheme.titleLarge),
          if (current['time'] != null) Text('Updated: ${current['time']} ${weather?['timezone_abbreviation'] ?? weather?['timezone'] ?? ''}'),
          for (final entry in {'temperature_2m': 'Temperature', 'apparent_temperature': 'Feels like',
            'relative_humidity_2m': 'Humidity', 'wind_speed_10m': 'Wind', 'precipitation': 'Precipitation'}.entries)
            if (current[entry.key] != null) Text('${entry.value}: ${current[entry.key]} ${units[entry.key] ?? ''}'),
        ])),
        if (weather != null && days.isEmpty && current.isEmpty) const Text('No weather observations or forecast are available for this location.'),
        if (hasTrip && !days.any((day) => inTrip(day.toString()))) const Text('A forecast is not available for your trip dates yet. Check again closer to departure.'),
        for (var i = 0; i < days.length; i++) Padding(padding: const EdgeInsets.only(top: 10),
          child: InkCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${days[i]} — ${conditions(dailyValue(daily, 'weather_code', i))}'),
            if (dailyValue(daily, 'temperature_2m_min', i) != null) Text('Low: ${dailyValue(daily, 'temperature_2m_min', i)} °C'),
            if (dailyValue(daily, 'temperature_2m_max', i) != null) Text('High: ${dailyValue(daily, 'temperature_2m_max', i)} °C'),
            if (dailyValue(daily, 'precipitation_probability_max', i) != null) Text('Rain probability: ${dailyValue(daily, 'precipitation_probability_max', i)}%'),
            if (hasTrip && inTrip(days[i].toString()) && dailyValue(daily, 'weather_code', i) is num &&
                dailyValue(daily, 'precipitation_probability_max', i) is num && dailyValue(daily, 'temperature_2m_max', i) is num)
              Text(adviceForDay((dailyValue(daily, 'weather_code', i) as num).toInt(),
                (dailyValue(daily, 'precipitation_probability_max', i) as num).toInt(),
                (dailyValue(daily, 'temperature_2m_max', i) as num).toDouble(), outdoorStops)),
          ]))),
      ]));
  }
}
