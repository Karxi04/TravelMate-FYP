import '../../core/utils/malaysian_locations.dart';
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
  late String _lastInput;
  final focus = FocusNode();
  late final ApiService api;
  Map<String, dynamic>? selectedLocation;
  Map<String, dynamic>? weather;
  String? error;
  Future<void> Function()? retryAction;
  bool busy = false;
  int version = 0;
  List<Map<String, dynamic>> catalogue = [];
  bool loadingLocations = true;
  String? stateNotice;
  int suggestionVersion = 0;
  String locationName(Map<String, dynamic> item) => (item['label'] ??
          [item['name'], item['admin1'], item['country']]
              .where((v) => v != null && '$v'.isNotEmpty)
              .join(', '))
      .toString();

  Future<void> loadLocations() async {
    setState(() {
      loadingLocations = true;
      error = null;
    });
    try {
      final data = await api.get('/api/fr6/locations');
      if (!mounted) return;
      setState(() => catalogue = (data['results'] as List? ?? [])
          .whereType<Map>()
          .where((v) => v['country'] == 'Malaysia')
          .map((v) => Map<String, dynamic>.from(v))
          .toList());
    } catch (e) {
      if (mounted) setState(() { error = userFacingApiError(e); retryAction = loadLocations; });
    } finally {
      if (mounted) setState(() => loadingLocations = false);
    }
  }

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    place = TextEditingController(text: widget.initialPlace ?? '');
    _lastInput = place.text;
    loadLocations();
    place.addListener(() {
      if (place.text == _lastInput) return;
      _lastInput = place.text;
      version++;
      setState(() {
        busy = false;
        error = null;
        stateNotice = null;
        if (selectedLocation != null &&
            place.text != locationName(selectedLocation!)) {
          selectedLocation = null;
          weather = null;
        }
      });
    });
  }

  @override
  void dispose() {
    version++;
    suggestionVersion++;
    place.dispose();
    focus.dispose();
    super.dispose();
  }

  Iterable<Map<String, dynamic>> locations(TextEditingValue value) {
    if (value.text.trim().length < 2) return const [];
    final query = _locationKey(value.text);
    final matches = catalogue.where((row) =>
        row['requiresCity'] == true &&
        [row['name'], locationName(row), ...?row['aliases'] as List?]
            .any((name) => _locationKey(name) == query));
    if (matches.isNotEmpty) {
      final region = matches.first;
      return [region, ..._regionalPoints(region).take(8)];
    }
    return matchingMalaysianLocations(
        catalogue
            .map((v) => {
                  ...v,
                  'city': v['name'],
                  'state': v['admin1'],
                  'canonicalName': locationName(v)
                })
            .toList(),
        value.text);
  }

  String _locationKey(Object? value) => (value ?? '')
      .toString()
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
      .trim()
      .replaceFirst(RegExp(r' malaysia$'), '');

  List<Map<String, dynamic>> _regionalPoints(Map<String, dynamic> region) {
    return catalogue
        .where((row) =>
            row['admin1'] == region['admin1'] &&
            row['requiresCity'] != true &&
            row['latitude'] is num &&
            row['longitude'] is num)
        .toList()
      ..sort((a, b) {
        final byPopulation = ((b['population'] as num?) ?? 0)
            .compareTo((a['population'] as num?) ?? 0);
        return byPopulation != 0
            ? byPopulation
            : locationName(a).compareTo(locationName(b));
      });
  }

  Future<Map<String, dynamic>?> _chooseLocation(
      String title, List<Map<String, dynamic>> rows,
      {String? guidance}) {
    focus.unfocus();
    return showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        builder: (context) => SafeArea(
                child: Column(mainAxisSize: MainAxisSize.min, children: [
              ListTile(
                  title: Text(title),
                  subtitle: guidance == null ? null : Text(guidance)),
              Flexible(
                  child: ListView.builder(
                      shrinkWrap: true,
                      itemCount: rows.length,
                      itemBuilder: (context, index) {
                        final row = rows[index];
                        return ListTile(
                            title: Text(locationName(row)),
                            onTap: () => Navigator.pop(context, row));
                      })),
            ])));
  }

  Future<void> findMore() async {
    final query = place.text.trim();
    if (query.length < 3) {
      setState(() => error = 'Enter at least three letters.');
      return;
    }
    final request = ++suggestionVersion;
    final inputVersion = version;
    setState(() {
      loadingLocations = true;
      error = null;
    });
    try {
      final data = await api
          .get('/api/fr6/locations/search', {'q': query, 'remote': 'true'});
      if (!mounted || request != suggestionVersion || inputVersion != version)
        return;
      final rows = (data['results'] as List? ?? [])
          .whereType<Map>()
          .where((v) => v['country'] == 'Malaysia')
          .map((v) => Map<String, dynamic>.from(v))
          .toList();
      setState(() {
        final ids = catalogue.map((v) => v['id']).toSet();
        catalogue.addAll(rows.where((v) => ids.add(v['id'])));
        stateNotice = rows.isEmpty
            ? 'No verified Malaysian location found. Try a nearby named locality.'
            : null;
      });
      if (rows.isNotEmpty) {
        final choice = await _chooseLocation('Malaysian locations', rows);
        if (mounted && inputVersion == version && choice != null) {
          await selectLocation(choice);
        }
      }
    } catch (e) {
      if (mounted && inputVersion == version)
        setState(() {
          error = userFacingApiError(e);
          retryAction = findMore;
        });
    } finally {
      if (mounted && request == suggestionVersion)
        setState(() => loadingLocations = false);
    }
  }

  Future<void> selectLocation(Map<String, dynamic> location) async {
    if (location['requiresCity'] == true) {
      final region = location;
      final selectionVersion = version;
      final points = _regionalPoints(region);
      final point = await _chooseLocation(
          "Choose a locality in " + region['admin1'].toString(), points,
          guidance: points.isEmpty
              ? 'No verified forecast locations are available for this area.'
              : 'Choose a city or locality; weather varies across the state.');
      if (!mounted || selectionVersion != version || point == null) return;
      location = point;
    }
    focus.unfocus();
    place.text = locationName(location);
    setState(() {
      selectedLocation = location;
      weather = null;
      error = null;
      stateNotice = location['pointDescription']?.toString();
    });
  }

  bool get canForecast =>
      selectedLocation != null &&
      selectedLocation!['requiresCity'] != true &&
      place.text == locationName(selectedLocation!);

  Future<void> search() async {
    if (!canForecast) return;
    final request = ++version;
    setState(() {
      busy = true;
      error = null;
      weather = null;
    });
    try {
      final data = await api.get('/api/fr6/weather', {
        'latitude': '${selectedLocation!['latitude']}',
        'longitude': '${selectedLocation!['longitude']}',
        if (selectedLocation!['id'] != null)
          'locationId': '${selectedLocation!['id']}',
        'locationName': locationName(selectedLocation!)
      });
      if (!mounted || request != version) return;
      setState(
          () => weather = Map<String, dynamic>.from(data['weather'] as Map));
    } catch (e) {
      if (mounted && request == version)
        setState(() {
          error = userFacingApiError(e);
          retryAction = search;
        });
    } finally {
      if (mounted && request == version) setState(() => busy = false);
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
        const SectionTitle('Destination weather', subtitle: 'Choose a Malaysian city or locality.'),
        LayoutBuilder(builder: (context, constraints) => RawAutocomplete<Map<String, dynamic>>(
          textEditingController: place, focusNode: focus, displayStringForOption: locationName,
          optionsBuilder: locations,
          onSelected: selectLocation,
          fieldViewBuilder: (_, controller, node, submit) => TextField(controller: controller, focusNode: node,
            decoration: const InputDecoration(labelText: 'Destination', hintText: 'Search Malaysian city or locality'), onSubmitted: (_) => submit()),
          optionsViewBuilder: (_, select, options) => Align(alignment: Alignment.topLeft,
            child: Material(elevation: 4, child: SizedBox(width: constraints.maxWidth, height: 210,
              child: ListView(padding: EdgeInsets.zero, children: options.map((item) => ListTile(
                title: Text(locationName(item)),
                subtitle: Text(item['requiresCity'] == true ? 'State or territory — choose a locality' : 'Locality point forecast'), onTap: () => select(item))).toList())))),
        )),
        if (loadingLocations) const LinearProgressIndicator(),
        if (stateNotice != null) Text(stateNotice!),
        if (!loadingLocations && selectedLocation == null && place.text.trim().length >= 2 && locations(place.value).isEmpty)
          const Text('No local matches. Try Find more Malaysian locations.'),
        TextButton(onPressed: loadingLocations ? null : findMore, child: const Text('Find more Malaysian locations')),
        const SizedBox(height: 12),
        FilledButton(onPressed: busy || !canForecast ? null : search, child: Text(busy ? 'Loading forecast...' : 'Show weather')),
        if (error != null) AppErrorState(message: error!, onRetry: retryAction ?? search),
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
            Text('${days[i]} \u2014 ${conditions(dailyValue(daily, 'weather_code', i))}'),
            if (dailyValue(daily, 'temperature_2m_min', i) != null) Text('Low: ${dailyValue(daily, 'temperature_2m_min', i)} \u00b0C'),
            if (dailyValue(daily, 'temperature_2m_max', i) != null) Text('High: ${dailyValue(daily, 'temperature_2m_max', i)} \u00b0C'),
            if (dailyValue(daily, 'precipitation_probability_max', i) != null) Text('Rain probability: ${dailyValue(daily, 'precipitation_probability_max', i)}%'),
            if (hasTrip && inTrip(days[i].toString()) && dailyValue(daily, 'weather_code', i) is num &&
                dailyValue(daily, 'precipitation_probability_max', i) is num && dailyValue(daily, 'temperature_2m_max', i) is num)
              Text(adviceForDay((dailyValue(daily, 'weather_code', i) as num).toInt(),
                (dailyValue(daily, 'precipitation_probability_max', i) as num).toInt(),
                (dailyValue(daily, 'temperature_2m_max', i) as num).toDouble(), outdoorStops)),
          ]))),
        const ExpansionTile(title: Text('Data sources'), children: [
          Padding(padding: EdgeInsets.all(12), child: Text('Weather forecasts by Open-Meteo.')),
        ]),
      ]));
  }
}
