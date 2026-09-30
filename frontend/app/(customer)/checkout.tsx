import { useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import * as WebBrowser from "expo-web-browser";
import * as Location from "expo-location";
import { useQuery } from "@tanstack/react-query";
import { colors, spacing, radius } from "@/src/theme";
import { useCart } from "@/src/cart";
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";

const METHODS = [
  { key: "in_house", label: "In-House Delivery", desc: "Shop's own rider · live tracking", icon: "🛵" },
  { key: "third_party", label: "Third-Party Courier", desc: "Delivered via courier partner", icon: "📦" },
  { key: "pickup", label: "Pick-Up", desc: "Collect at the flower shop", icon: "🏪" },
];

export default function Checkout() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { items, total, clear } = useCart();
  const { user } = useAuth();
  const { data: shops = [] } = useQuery({ queryKey: ["shops"], queryFn: () => api("/shops") });

  const [contactName, setContactName] = useState(user?.name || "");
  const [contactPhone, setContactPhone] = useState("");
  const [addr, setAddr] = useState("San Antonio, Biñan, Laguna");
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [notes, setNotes] = useState("");
  const [method, setMethod] = useState("in_house");
  const [pay, setPay] = useState<"cod" | "gcash">("gcash");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const validItems = items.filter((i) => i.shop_id && i.shop_id !== "custom");

  // allowed methods = intersection of methods across shops in cart
  const allowed = useMemo(() => {
    const cartShops = new Set(validItems.map((i) => i.shop_id));
    const lists = shops.filter((s: any) => cartShops.has(s.id)).map((s: any) => s.delivery_methods || []);
    if (!lists.length) return METHODS.map((m) => m.key);
    return METHODS.map((m) => m.key).filter((k) => lists.every((l: string[]) => l.includes(k)));
  }, [shops, validItems]);

  const useMyLocation = async () => {
    const perm = await Location.requestForegroundPermissionsAsync();
    if (!perm.granted) { setErr("Location permission helps the rider find you."); return; }
    try { const pos = await Location.getCurrentPositionAsync({}); setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude }); }
    catch { setErr("Could not get location"); }
  };

  const placeOrder = async () => {
    if (validItems.length === 0) { setErr("Your cart has no shop items."); return; }
    if (!contactName.trim()) { setErr("Please enter your full name."); return; }
    const phoneDigits = contactPhone.replace(/\D/g, "");
    if (phoneDigits.length < 7) { setErr("Please enter a valid contact phone number."); return; }
    const chosen = allowed.includes(method) ? method : allowed[0];
    if (chosen !== "pickup" && !addr) { setErr("Please enter a delivery address"); return; }
    setLoading(true); setErr(null);
    try {
      const order = await api("/orders", { method: "POST", body: JSON.stringify({
        items: validItems.map((i) => ({ product_id: i.product_id, shop_id: i.shop_id, name: i.name, image: i.image, unit_price: i.unit_price, quantity: i.quantity })),
        contact_name: contactName.trim(), contact_phone: contactPhone.trim(),
        delivery_method: chosen,
        delivery_address: chosen === "pickup" ? "Pick-Up at shop" : addr,
        delivery_lat: coords?.lat ?? 14.3419, delivery_lng: coords?.lng ?? 121.0803,
        notes, payment_method: pay,
      }) });
      clear();
      if (pay === "gcash") {
        const res = await api(`/orders/${order.id}/pay/gcash`, { method: "POST" });
        if (res?.redirect_url) {
          await WebBrowser.openBrowserAsync(res.redirect_url);
        }
      } else {
        await api(`/orders/${order.id}/pay/cod`, { method: "POST" });
      }
      router.replace(`/(customer)/track/${order.id}` as any);
    } catch (e: any) { setErr(e.message); }
    finally { setLoading(false); }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="back-btn" onPress={() => router.back()}><Text style={styles.back}>←</Text></Pressable>
        <Text style={styles.title}>Checkout</Text>
        <View style={{ width: 24 }} />
      </View>
      <KeyboardAwareScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg, paddingBottom: 200 }} keyboardShouldPersistTaps="handled" bottomOffset={20}>
        <View>
          <Text style={styles.section}>Contact Details</Text>
          <Text style={styles.fieldLabel}>Full Name *</Text>
          <TextInput testID="contact-name-input" value={contactName} onChangeText={setContactName} placeholder="Juan Dela Cruz" placeholderTextColor={colors.muted} style={styles.input} />
          <Text style={[styles.fieldLabel, { marginTop: spacing.sm }]}>Phone Number *</Text>
          <TextInput testID="contact-phone-input" value={contactPhone} onChangeText={setContactPhone} placeholder="0917 123 4567" placeholderTextColor={colors.muted} keyboardType="phone-pad" style={styles.input} />
        </View>

        <View>
          <Text style={styles.section}>Delivery Method</Text>
          {METHODS.filter((m) => allowed.includes(m.key)).map((m) => (
            <Pressable key={m.key} testID={`method-${m.key}`} onPress={() => setMethod(m.key)} style={[styles.opt, method === m.key && styles.optActive]}>
              <Text style={{ fontSize: 20 }}>{m.icon}</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.optTitle}>{m.label}</Text>
                <Text style={styles.optSub}>{m.desc}</Text>
              </View>
              <View style={[styles.radio, method === m.key && styles.radioOn]} />
            </Pressable>
          ))}
        </View>

        {method !== "pickup" && (
          <View>
            <Text style={styles.section}>Delivery Address</Text>
            <TextInput testID="address-input" value={addr} onChangeText={setAddr} multiline style={styles.input} placeholderTextColor={colors.muted} />
            <Pressable testID="pin-loc-btn" onPress={useMyLocation} style={styles.pinBtn}>
              <Text style={styles.pinText}>📍 {coords ? `Pinned (${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)})` : "Pin my current location"}</Text>
            </Pressable>
          </View>
        )}

        <View>
          <Text style={styles.section}>Order Notes</Text>
          <TextInput testID="notes-input" value={notes} onChangeText={setNotes} placeholder="Any special requests?" multiline style={styles.input} placeholderTextColor={colors.muted} />
        </View>

        <View>
          <Text style={styles.section}>Payment Method</Text>
          <Pressable testID="pay-gcash" onPress={() => setPay("gcash")} style={[styles.opt, pay === "gcash" && styles.optActive]}>
            <Text style={{ fontSize: 20 }}>📱</Text>
            <View style={{ flex: 1 }}><Text style={styles.optTitle}>GCash</Text><Text style={styles.optSub}>Pay online via GCash checkout</Text></View>
            <View style={[styles.radio, pay === "gcash" && styles.radioOn]} />
          </Pressable>
          <Pressable testID="pay-cod" onPress={() => setPay("cod")} style={[styles.opt, pay === "cod" && styles.optActive]}>
            <Text style={{ fontSize: 20 }}>💵</Text>
            <View style={{ flex: 1 }}><Text style={styles.optTitle}>Cash on Delivery</Text><Text style={styles.optSub}>Pay when your bouquet arrives</Text></View>
            <View style={[styles.radio, pay === "cod" && styles.radioOn]} />
          </Pressable>
        </View>

        <View style={styles.summaryBox}>
          <Text style={styles.section}>Order Summary</Text>
          {validItems.map((i) => (
            <View key={i.product_id} style={styles.sumRow}>
              <Text style={styles.sumItem} numberOfLines={1}>{i.name} × {i.quantity}</Text>
              <Text style={styles.sumPrice}>₱{(i.unit_price * i.quantity).toLocaleString()}</Text>
            </View>
          ))}
          <View style={[styles.sumRow, { marginTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.sm }]}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.totalPrice}>₱{total.toLocaleString()}</Text>
          </View>
        </View>
        {err ? <Text testID="checkout-error" style={{ color: colors.error }}>{err}</Text> : null}
      </KeyboardAwareScrollView>
      <View style={[styles.footer, { paddingBottom: insets.bottom + spacing.md }]}>
        <Pressable testID="place-order-btn" onPress={placeOrder} disabled={loading} style={styles.cta}>
          <LinearGradient colors={["#FF7EB3", "#FF758C"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.ctaBg}>
            {loading ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.ctaText}>{pay === "gcash" ? "Pay with GCash" : "Place Order"} · ₱{total.toLocaleString()}</Text>}
          </LinearGradient>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider },
  back: { fontSize: 22, color: colors.onSurface },
  title: { fontSize: 18, fontWeight: "700", color: colors.onSurface },
  section: { fontSize: 14, fontWeight: "700", color: colors.onSurface, marginBottom: spacing.sm },
  fieldLabel: { fontSize: 12, fontWeight: "600", color: colors.onSurfaceSecondary, marginBottom: 6 },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 12, minHeight: 48, color: colors.onSurface, fontSize: 14 },
  pinBtn: { marginTop: spacing.sm, backgroundColor: colors.brandTertiary, paddingVertical: 10, borderRadius: radius.pill, alignItems: "center" },
  pinText: { color: colors.onBrandTertiary, fontWeight: "700", fontSize: 12 },
  opt: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm, backgroundColor: colors.surfaceSecondary },
  optActive: { borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary },
  optTitle: { fontSize: 14, fontWeight: "700", color: colors.onSurface },
  optSub: { fontSize: 12, color: colors.muted, marginTop: 2 },
  radio: { width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: colors.borderStrong },
  radioOn: { borderColor: colors.brandPrimary, backgroundColor: colors.brandPrimary },
  summaryBox: { padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md },
  sumRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  sumItem: { flex: 1, color: colors.onSurface, fontSize: 13 },
  sumPrice: { color: colors.onSurface, fontWeight: "600", fontSize: 13 },
  totalLabel: { fontSize: 15, fontWeight: "700", color: colors.onSurface },
  totalPrice: { fontSize: 18, fontWeight: "700", color: colors.brandPrimary },
  footer: { position: "absolute", left: 0, right: 0, bottom: 0, padding: spacing.lg, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.divider },
  cta: { borderRadius: radius.pill, overflow: "hidden" },
  ctaBg: { paddingVertical: 14, alignItems: "center" },
  ctaText: { color: "#FFFFFF", fontWeight: "700", fontSize: 15 },
});
