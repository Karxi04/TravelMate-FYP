DateTime malaysiaPackageToday([DateTime? now]) {
  final date=(now ?? DateTime.now()).toUtc().add(const Duration(hours:8));
  return DateTime.utc(date.year,date.month,date.day);
}

bool packageDepartureAvailable(String value,{DateTime? now}) {
  if(!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) return false;
  final parsed=DateTime.tryParse(value);
  if(parsed==null || parsed.toIso8601String().substring(0,10)!=value) return false;
  return !DateTime.utc(parsed.year,parsed.month,parsed.day).isBefore(malaysiaPackageToday(now));
}

String? packageDepartureError(List<String> dates,String? selected,{DateTime? now}) {
  if(dates.isNotEmpty && !dates.any((date)=>packageDepartureAvailable(date,now:now))) {
    return 'No current or upcoming package departures are available. Checkout is unavailable.';
  }
  if(dates.isNotEmpty && (selected==null || !dates.contains(selected))) return 'Select a supported departure date.';
  if(selected!=null && !packageDepartureAvailable(selected,now:now)) return 'This departure date has passed or is invalid in Malaysia. Choose a valid supported date.';
  return null;
}
