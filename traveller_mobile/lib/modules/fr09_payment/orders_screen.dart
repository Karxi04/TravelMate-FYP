import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';

class OrdersScreen extends StatefulWidget {
  final ApiService? api;
  final String? orderId;
  const OrdersScreen({super.key, this.api, this.orderId});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  late final api = widget.api ?? ApiService();
  List<Map<String, dynamic>> orders = [];
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load({bool reconcile = false}) async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final id = widget.orderId;
      final data = await api.get(id == null
          ? '/api/fr9/orders'
          : '/api/fr9/orders/${Uri.encodeComponent(id)}${reconcile ? '/reconcile' : ''}');
      final items = id == null ? data['items'] as List : [data['order']];
      if (!mounted) return;
      setState(() => orders =
          items.map((item) => Map<String, dynamic>.from(item as Map)).toList());
    } catch (e) {
      if (mounted) setState(() => error = userFacingApiError(e));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final details = widget.orderId != null;
    return Scaffold(
      appBar:
          AppBar(title: Text(details ? 'Order details' : 'Orders'), actions: [
        IconButton(
            tooltip: 'Refresh',
            onPressed: loading ? null : load,
            icon: const Icon(Icons.refresh)),
      ]),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : error != null
              ? Center(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(error!),
                  TextButton(onPressed: load, child: const Text('Try again')),
                ]))
              : RefreshIndicator(
                  onRefresh: load,
                  child: ListView(
                      padding: const EdgeInsets.all(18),
                      physics: const AlwaysScrollableScrollPhysics(),
                      children: [
                        if (orders.isEmpty)
                          const Text('No Checkout orders yet.'),
                        for (final order in orders)
                          if (details) ...[
                            Text('${order['currency']} ${order['amount']}',
                                style:
                                    Theme.of(context).textTheme.headlineSmall),
                            const SizedBox(height: 12),
                            Text('Order: ${order['id']}'),
                            Text('Status: ${order['status']}'),
                            Text('Payment: ${order['paymentStatus']}'),
                            Text('Type: ${order['quoteType']}'),
                            if (order['createdAt'] != null)
                              Text('Created: ${order['createdAt']}'),
                            if (order['quoteSnapshot'] is Map)
                              for (final field in const {
                                'name': 'Hotel or itinerary',
                                'roomName': 'Room',
                                'boardName': 'Board',
                                'taxesAndFeesStatus': 'Taxes and fees'
                              }.entries)
                                if ((order['quoteSnapshot']
                                        as Map)[field.key] !=
                                    null)
                                  Text(
                                      '${field.value}: ${(order['quoteSnapshot'] as Map)[field.key]}'),
                            if (order['status'] == 'paid')
                              const Text(
                                  'Payment confirmed. No further payment is required.'),
                            if (order['provider'] == 'stripe_checkout_test')
                              const Text(
                                  'Stripe test-mode payment; no real money is charged.'),
                            if (order['sandbox'] == true)
                              const Text(
                                  'Provider sandbox quote; this is not a live hotel reservation.'),
                            if ({
                              'checkout_open',
                              'payment_pending',
                              'checkout_pending'
                            }.contains(order['status']))
                              TextButton(
                                  onPressed: () => load(reconcile: true),
                                  child: const Text('Check payment status')),
                          ] else
                            InkCard(
                                child: ListTile(
                              title: Text(
                                  '${order['quoteType']} · ${order['currency']} ${order['amount']}'),
                              subtitle: Text('${order['status']}'),
                              trailing: const Icon(Icons.chevron_right),
                              onTap: () async {
                                await Navigator.of(context).push(
                                    MaterialPageRoute<void>(
                                        builder: (_) => OrdersScreen(
                                            api: api,
                                            orderId: order['id'].toString())));
                                if (mounted) await load();
                              },
                            )),
                      ]),
                ),
    );
  }
}
