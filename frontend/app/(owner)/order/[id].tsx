import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform, Linking } from "react-native";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as Location from "expo-location";
import * as ImagePicker from "expo-image-picker";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { colors, spacing, radius } from "@/src/theme";
import { api, mediaUrl } from "@/src/api";
import { uploadFile } from "@/src/upload";
import LiveTrackMap from "@/src/components/LiveTrackMap";

const LABEL: Record<string, string> = {
  pending: "Pending", confirmed: "Confirmed", preparing: "Preparing",
  ready_for_delivery: "Ready to Deliver", ready_for_pickup: "Ready for Pickup",
  handed_to_courier: "Handed to Courier", out_for_delivery: "Out for Delivery", completed: "Completed",
};

export default function OwnerOrderDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const [locBusy, setLocBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [proofBusy, setProofBusy] = useState(false);
  const [proofMsg, setProofMsg] = useState<string | null>(null);
  const [proofBlocked, setProofBlocked] = useState(false);
  const { data: o, isLoading } = useQuery({ queryKey: ["owner-order", id], queryFn: () => api(`/orders/${id}`), enabled: !!id, refetchInterval: 6000 });
  const { data: track } = useQuery({ queryKey: ["owner-track", id], queryFn: () => api(`/orders/${id}/tracking`), enabled: !!id, refetchInterval: 5000 });

  const statusMut = useMutation({
    mutationFn: (status: string) => api(`/owner/orders/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["owner-order", id] }); qc.invalidateQueries({ queryKey: ["owner-orders"] }); },
  });
  const riderMut = useMutation({
    mutationFn: (c: { lat: number; lng: number }) => api(`/owner/orders/${id}/rider`, { method: "PATCH", body: JSON.stringify(c) }),
    onSuccess: () => { setMsg("Location shared with customer ✓"); qc.invalidateQueries({ queryKey: ["owner-order", id] }); },
  });
  const proofMut = useMutation({
    mutationFn: (url: string) => api(`/owner/orders/${id}/proof`, { method: "PATCH", body: JSON.stringify({ photo_url: url }) }),
    onSuccess: () => { setProofMsg("Delivery photo sent to customer ✓"); qc.invalidateQueries({ queryKey: ["owner-order", id] }); },
    onError: (e: any) => setProofMsg(e.message),
  });

  if (isLoading || !o) return <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>;

  const flow: string[] = o.status_flow || ["pending", "confirmed", "preparing", "ready_for_delivery", "out_for_delivery", "completed"];
  const idx = flow.indexOf(o.status);
  const next = idx >= 0 && idx < flow.length - 1 ? flow[idx + 1] : null;

  const shareLocation = async () => {
    setMsg(null);
    const perm = await Location.requestForegroundPermissionsAsync();
    if (!perm.granted) { setMsg("Location permission needed to share your position."); return; }
    setLocBusy(true);
    try { const pos = await Location.getCurrentPositionAsync({}); riderMut.mutate({ lat: pos.coords.latitude, lng: pos.coords.longitude }); }
    catch { setMsg("Could not get location"); } finally { setLocBusy(false); }
  };

  const addProof = async () => {
    setProofMsg(null); setProofBlocked(false);
    let uri: string | null = null;
    if (Platform.OS === "web") {
      const lib = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!lib.granted) { setProofMsg("Photo permission is needed to attach a delivery photo."); setProofBlocked(!lib.canAskAgain); return; }
      const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.6 });
      if (r.canceled || !r.assets?.length) return;
      uri = r.assets[0].uri;
    } else {
      const cam = await ImagePicker.requestCameraPermissionsAsync();
      if (cam.granted) {
        const r = await ImagePicker.launchCameraAsync({ quality: 0.6 });
        if (r.canceled || !r.assets?.length) return;
        uri = r.assets[0].uri;
      } else {
        // Camera denied — fall back to the gallery so the owner isn't dead-ended.
        const lib = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!lib.granted) {
          setProofMsg("Camera and photo access are off. Enable them in Settings to attach a delivery photo.");
          setProofBlocked(!cam.canAskAgain || !lib.canAskAgain);
          return;
        }
        const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.6 });
        if (r.canceled || !r.assets?.length) return;
        uri = r.assets[0].uri;
      }
    }
    if (!uri) return;
    setProofBusy(true);
    try { const up = await uploadFile(uri, "delivery-proof.jpg", "image/jpeg"); proofMut.mutate(up.url); }
    catch (e: any) { setProofMsg(e.message); }
    finally { setProofBusy(false); }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="back-btn" onPress={() => router.back()}><Text style={styles.back}>←</Text></Pressable>
        <Text style={styles.title}>{o.order_no}</Text>
        <View style={{ width: 24 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg, paddingBottom: insets.bottom + spacing.xxl }}>
        <View style={styles.box}>
          <Row k="Customer" v={o.contact_name || o.customer_name} />
          {o.contact_phone ? <Row k="Phone" v={o.contact_phone} /> : null}
          <Row k="Delivery" v={{ in_house: "In-House Delivery", third_party: "Third-Party", pickup: "Pick-Up" }[o.delivery_method as string] || o.delivery_method} />
          <Row k="Payment" v={o.payment_status === "paid" ? `Paid (${o.payment_ref || "GCash"})` : o.payment_method === "gcash" ? "GCash · unpaid" : "Cash on Delivery"} />
          {o.delivery_method !== "pickup" && <Row k="Address" v={o.delivery_address} />}
          {o.notes ? <Row k="Notes" v={o.notes} /> : null}
        </View>

        <Pressable testID="message-customer-btn" onPress={() => router.push(`/(owner)/chat/${o.id}` as any)} style={styles.msgCustomerBtn}>
          <Text style={styles.msgCustomerText}>💬 Message Customer</Text>
        </Pressable>

        <View style={styles.box}>
          <Text style={styles.section}>Items</Text>
          {o.items.map((it: any, i: number) => (
            <View key={i} style={styles.itemRow}>
              <Text style={styles.itemName} numberOfLines={1}>{it.name} × {it.quantity}</Text>
              <Text style={styles.itemPrice}>₱{(it.unit_price * it.quantity).toLocaleString()}</Text>
            </View>
          ))}
          <View style={[styles.itemRow, { borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.sm, marginTop: spacing.xs }]}>
            <Text style={styles.totalLabel}>Total</Text><Text style={styles.totalPrice}>₱{o.total.toLocaleString()}</Text>
          </View>
        </View>

        <View>
          <Text style={styles.section}>Order Progress</Text>
          <View style={styles.stepper}>
            {flow.map((s, i) => (
              <View key={s} style={styles.step}>
                <View style={[styles.dot, i <= idx && { backgroundColor: colors.brandPrimary }]}>
                  {i <= idx && <Text style={{ color: "#FFF", fontSize: 10, fontWeight: "800" }}>✓</Text>}
                </View>
                <Text style={[styles.stepLabel, i === idx && { color: colors.brandPrimary, fontWeight: "700" }]}>{LABEL[s] || s}</Text>
              </View>
            ))}
          </View>
          {next && (
            <Pressable testID="advance-btn" onPress={() => statusMut.mutate(next)} disabled={statusMut.isPending} style={styles.advBtn}>
              <Text style={styles.advText}>{statusMut.isPending ? "Updating..." : `Mark as ${LABEL[next]} →`}</Text>
            </Pressable>
          )}
        </View>

        {o.delivery_method === "in_house" && (
          <View>
            <Text style={styles.section}>In-House Delivery Tracking</Text>
            <View style={styles.trackMetaBox}>
              <Text style={styles.trackStatus}>
                {o.status === "completed" ? "✓ Delivered / received"
                  : track?.moving ? `🛵 Out for delivery · ETA ~${track.eta_min} min`
                  : `Status: ${LABEL[o.status] || o.status}`}
              </Text>
              <Text style={styles.trackAddr}>📍 {o.delivery_address}</Text>
              {track?.lat != null && (
                <Text style={styles.trackCoords}>Rider position: {Number(track.lat).toFixed(5)}, {Number(track.lng).toFixed(5)}</Text>
              )}
            </View>
            <View style={{ height: 180, borderRadius: radius.md, overflow: "hidden", marginTop: spacing.sm }}>
              <LiveTrackMap orderId={o.id} riderEmoji="🛵" />
            </View>
            <Pressable testID="share-loc-btn" onPress={shareLocation} disabled={locBusy || riderMut.isPending} style={styles.locBtn}>
              <Text style={styles.locText}>{locBusy || riderMut.isPending ? "Sharing..." : "📍 Share my live location"}</Text>
            </Pressable>
            {msg ? <Text style={styles.msg}>{msg}</Text> : null}
          </View>
        )}

        {o.delivery_method !== "pickup" && (
          <View>
            <Text style={styles.section}>Delivery Proof Photo</Text>
            {o.proof_photo ? (
              <Image source={{ uri: mediaUrl(o.proof_photo) }} style={styles.proofImg} contentFit="cover" testID="proof-photo" />
            ) : (
              <Text style={styles.proofHint}>Snap a photo when you drop off the flowers so the customer sees proof of delivery.</Text>
            )}
            <Pressable testID="add-proof-btn" onPress={addProof} disabled={proofBusy || proofMut.isPending} style={styles.proofBtn}>
              <Text style={styles.proofBtnText}>
                {proofBusy || proofMut.isPending ? "Uploading..." : o.proof_photo ? "📸 Replace delivery photo" : "📸 Add delivery photo"}
              </Text>
            </Pressable>
            {proofBlocked && (
              <Pressable testID="proof-settings-btn" onPress={() => Linking.openSettings()} style={styles.settingsBtn}>
                <Text style={styles.settingsText}>Open Settings</Text>
              </Pressable>
            )}
            {proofMsg ? <Text style={styles.msg}>{proofMsg}</Text> : null}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

function Row({ k, v }: { k: string; v: any }) {
  return <View style={styles.kv}><Text style={styles.k}>{k}</Text><Text style={styles.v}>{String(v)}</Text></View>;
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider },
  back: { fontSize: 22, color: colors.onSurface },
  title: { fontSize: 18, fontWeight: "700", color: colors.onSurface },
  box: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, gap: 6 },
  kv: { flexDirection: "row", justifyContent: "space-between", gap: spacing.md },
  k: { color: colors.muted, fontSize: 13 },
  v: { color: colors.onSurface, fontSize: 13, fontWeight: "600", flexShrink: 1, textAlign: "right" },
  section: { fontSize: 15, fontWeight: "700", color: colors.onSurface, marginBottom: spacing.sm },
  itemRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 3 },
  itemName: { flex: 1, color: colors.onSurface, fontSize: 13 },
  itemPrice: { color: colors.onSurface, fontWeight: "600", fontSize: 13 },
  totalLabel: { fontSize: 15, fontWeight: "700", color: colors.onSurface },
  totalPrice: { fontSize: 16, fontWeight: "700", color: colors.brandPrimary },
  stepper: { gap: spacing.xs, marginBottom: spacing.md },
  step: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: 4 },
  dot: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  stepLabel: { color: colors.onSurfaceSecondary, fontSize: 14 },
  advBtn: { backgroundColor: colors.brandPrimary, paddingVertical: 14, borderRadius: radius.pill, alignItems: "center" },
  advText: { color: colors.onBrandPrimary, fontWeight: "700", fontSize: 14 },
  locBtn: { marginTop: spacing.md, backgroundColor: colors.brandTertiary, paddingVertical: 12, borderRadius: radius.pill, alignItems: "center" },
  locText: { color: colors.onBrandTertiary, fontWeight: "700", fontSize: 13 },
  msg: { color: colors.success, fontSize: 12, marginTop: spacing.xs, textAlign: "center" },
  msgCustomerBtn: { backgroundColor: colors.brandTertiary, paddingVertical: 13, borderRadius: radius.pill, alignItems: "center" },
  msgCustomerText: { color: colors.onBrandTertiary, fontWeight: "800", fontSize: 13 },
  trackMetaBox: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, gap: 4 },
  trackStatus: { color: colors.onSurface, fontWeight: "700", fontSize: 13 },
  trackAddr: { color: colors.onSurfaceSecondary, fontSize: 13 },
  trackCoords: { color: colors.muted, fontSize: 11 },
  proofImg: { width: "100%", height: 220, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary },
  proofHint: { color: colors.muted, fontSize: 13, lineHeight: 19, marginBottom: spacing.sm },
  proofBtn: { marginTop: spacing.sm, backgroundColor: colors.brandPrimary, paddingVertical: 13, borderRadius: radius.pill, alignItems: "center" },
  proofBtnText: { color: colors.onBrandPrimary, fontWeight: "800", fontSize: 13 },
  settingsBtn: { marginTop: spacing.sm, borderWidth: 1, borderColor: colors.borderStrong, paddingVertical: 11, borderRadius: radius.pill, alignItems: "center" },
  settingsText: { color: colors.onSurface, fontWeight: "700", fontSize: 13 },
});
