import { View, Text, StyleSheet, ScrollView, Pressable, Dimensions, ActivityIndicator, RefreshControl } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useQuery } from "@tanstack/react-query";
import { colors, spacing, radius } from "@/src/theme";
import { api, mediaUrl } from "@/src/api";

const { width } = Dimensions.get("window");

export default function OwnerDashboard() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data: shop, isLoading, refetch, isRefetching } = useQuery({ queryKey: ["owner-application"], queryFn: () => api("/owner/application") });
  const { data: products = [] } = useQuery({ queryKey: ["my-products"], queryFn: () => api("/owner/products"), enabled: shop?.status === "approved" });
  const { data: orders = [] } = useQuery({ queryKey: ["owner-orders"], queryFn: () => api("/owner/orders"), refetchInterval: 8000, enabled: shop?.status === "approved" });
  const { data: notifs = [] } = useQuery({ queryKey: ["owner-notifs"], queryFn: () => api("/notifications"), refetchInterval: 8000 });
  const unread = notifs.filter((n: any) => !n.read).length;

  const Bell = ({ dark }: { dark?: boolean }) => (
    <Pressable testID="inbox-bell" onPress={() => router.push("/(owner)/inbox")} style={[styles.bell, dark && styles.bellDark]} hitSlop={8}>
      <Text style={{ fontSize: 20 }}>🔔</Text>
      {unread > 0 && <View style={styles.bellBadge}><Text style={styles.bellBadgeText}>{unread > 9 ? "9+" : unread}</Text></View>}
    </Pressable>
  );

  if (isLoading) return <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>;

  // ---- Not approved states ----
  if (!shop || shop.status === "none" || shop.status === "pending" || shop.status === "rejected") {
    return (
      <View style={{ flex: 1, backgroundColor: colors.surface }}>
        <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: insets.top + spacing.xl, gap: spacing.lg }}
          refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={colors.brandPrimary} />}>
          <View style={styles.topRow}>
            <Text style={styles.brand}>Elaya for Shops</Text>
            <Bell />
          </View>
          {(!shop || shop.status === "none") && (
            <StatusCard testID="status-none" emoji="🌱" title="Start selling on Elaya"
              body="Submit your shop application with your business permit and details. Our admin will review it before you can list bouquets."
              cta="Submit Application" onPress={() => router.push("/(owner)/application")} />
          )}
          {shop?.status === "pending" && (
            <StatusCard testID="status-pending" emoji="⏳" title="Pending approval" color={colors.warning}
              body={`Your application for "${shop.shop_name}" is under review by the Elaya admin. You'll be notified once it's approved.`}
              cta="View / Edit Application" onPress={() => router.push("/(owner)/application")} />
          )}
          {shop?.status === "rejected" && (
            <StatusCard testID="status-rejected" emoji="❌" title="Application rejected" color={colors.error}
              body={shop.reject_reason || "Your application did not meet the requirements."}
              cta="Re-apply" onPress={() => router.push("/(owner)/application")} />
          )}
          {notifs.length > 0 && <Notifs notifs={notifs} onSeeAll={() => router.push("/(owner)/inbox")} />}
        </ScrollView>
      </View>
    );
  }

  // ---- Approved dashboard ----
  const pending = orders.filter((o: any) => o.status === "pending").length;
  const paid = orders.filter((o: any) => o.payment_status === "paid").length;
  const revenue = orders.filter((o: any) => o.status === "completed").reduce((s: number, o: any) => s + o.total, 0);
  const lowStock = products.filter((p: any) => (p.stock ?? 0) <= 5).sort((a: any, b: any) => (a.stock ?? 0) - (b.stock ?? 0));

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <ScrollView contentContainerStyle={{ paddingBottom: spacing.xxl }}
        refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={colors.brandPrimary} />}>
        <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
          <Image source={{ uri: mediaUrl(shop?.image) }} style={StyleSheet.absoluteFillObject} contentFit="cover" />
          <LinearGradient colors={["rgba(43,30,34,0.5)", "rgba(43,30,34,0.9)"]} style={StyleSheet.absoluteFillObject} />
          <View style={styles.approvedBadge}><Text style={styles.approvedText}>✓ APPROVED</Text></View>
          <Text style={styles.shopName}>{shop?.shop_name}</Text>
          <Text style={styles.shopLoc}>📍 {shop?.location}</Text>
          <View style={[styles.bellFloat, { top: insets.top + spacing.md }]}><Bell dark /></View>
        </View>

        <View style={styles.metricGrid}>
          <Metric num={pending} label="Pending" />
          <Metric num={products.length} label="Products" />
          <Metric num={paid} label="Paid" />
          <Metric num={`₱${revenue.toLocaleString()}`} label="Revenue" />
        </View>

        <View style={styles.quickRow}>
          <Pressable testID="quick-add" onPress={() => router.push("/(owner)/add-bouquet")} style={styles.quick}>
            <Text style={{ fontSize: 26 }}>💐</Text><Text style={styles.quickLabel}>Add Bouquet</Text>
          </Pressable>
          <Pressable testID="quick-orders" onPress={() => router.push("/(owner)/orders")} style={styles.quick}>
            <Text style={{ fontSize: 26 }}>📋</Text><Text style={styles.quickLabel}>Orders</Text>
          </Pressable>
          <Pressable testID="quick-shop" onPress={() => router.push("/(owner)/profile")} style={styles.quick}>
            <Text style={{ fontSize: 26 }}>⚙️</Text><Text style={styles.quickLabel}>Shop Info</Text>
          </Pressable>
        </View>

        {notifs.length > 0 && <View style={{ paddingHorizontal: spacing.lg }}><Notifs notifs={notifs} onSeeAll={() => router.push("/(owner)/inbox")} /></View>}

        {lowStock.length > 0 && (
          <Pressable testID="low-stock-alert" onPress={() => router.push("/(owner)/products")} style={styles.lowCard}>
            <View style={styles.lowHead}>
              <Text style={styles.lowTitle}>⚠️ Low Stock Alert</Text>
              <Text style={styles.lowManage}>Manage →</Text>
            </View>
            <Text style={styles.lowSub}>{lowStock.length} bouquet{lowStock.length === 1 ? "" : "s"} need restocking soon</Text>
            {lowStock.slice(0, 4).map((p: any) => {
              const out = (p.stock ?? 0) <= 0;
              return (
                <View key={p.id} style={styles.lowRow} testID={`low-stock-${p.id}`}>
                  <Image source={{ uri: mediaUrl(p.image) }} style={styles.lowImg} contentFit="cover" />
                  <Text style={styles.lowName} numberOfLines={1}>{p.name}</Text>
                  <View style={[styles.lowBadge, { backgroundColor: out ? colors.error : colors.warning }]}>
                    <Text style={styles.lowBadgeText}>{out ? "OUT OF STOCK" : `${p.stock} left`}</Text>
                  </View>
                </View>
              );
            })}
            {lowStock.length > 4 && <Text style={styles.lowMore}>+{lowStock.length - 4} more</Text>}
          </Pressable>
        )}

        <Text style={styles.sectionTitle}>Recent Orders</Text>
        <View style={{ paddingHorizontal: spacing.lg, gap: spacing.sm }}>
          {orders.slice(0, 6).map((o: any) => (
            <Pressable key={o.id} testID={`dash-order-${o.id}`} onPress={() => router.push(`/(owner)/order/${o.id}` as any)} style={styles.orderRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.orderNo}>{o.order_no}</Text>
                <Text style={styles.orderCust}>{o.customer_name} · {o.items.length} items · {o.status.replace(/_/g, " ")}</Text>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={styles.orderPrice}>₱{o.total.toLocaleString()}</Text>
                <Text style={[styles.payTag, { color: o.payment_status === "paid" ? colors.success : colors.warning }]}>{o.payment_status === "paid" ? "PAID" : o.payment_method?.toUpperCase()}</Text>
              </View>
            </Pressable>
          ))}
          {orders.length === 0 && <Text style={{ color: colors.muted, textAlign: "center", marginTop: spacing.md }}>No orders yet today 💐</Text>}
        </View>
      </ScrollView>
    </View>
  );
}

function Metric({ num, label }: { num: any; label: string }) {
  return <View style={styles.metric}><Text style={styles.metricNum}>{num}</Text><Text style={styles.metricLabel}>{label}</Text></View>;
}

function Notifs({ notifs, onSeeAll }: { notifs: any[]; onSeeAll?: () => void }) {
  return (
    <View style={{ gap: spacing.sm }}>
      <View style={styles.notifHeadRow}>
        <Text style={styles.notifHead}>Recent Updates</Text>
        {onSeeAll && <Pressable testID="see-all-updates" onPress={onSeeAll}><Text style={styles.seeAll}>See all →</Text></Pressable>}
      </View>
      {notifs.slice(0, 4).map((n) => (
        <View key={n.id} style={[styles.notif, !n.read && styles.notifUnread]} testID={`notif-${n.id}`}>
          <Text style={styles.notifTitle}>{n.title}</Text>
          <Text style={styles.notifBody}>{n.body}</Text>
        </View>
      ))}
    </View>
  );
}

function StatusCard({ emoji, title, body, cta, onPress, color = colors.brandPrimary, testID }: any) {
  return (
    <View style={styles.statusCard} testID={testID}>
      <Text style={{ fontSize: 52 }}>{emoji}</Text>
      <Text style={[styles.statusTitle, { color }]}>{title}</Text>
      <Text style={styles.statusBody}>{body}</Text>
      <Pressable testID="status-cta" onPress={onPress} style={styles.statusCta}>
        <LinearGradient colors={["#FF7EB3", "#FF758C"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.statusCtaBg}>
          <Text style={styles.statusCtaText}>{cta}</Text>
        </LinearGradient>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  brand: { fontSize: 30, fontWeight: "300", fontStyle: "italic", color: colors.onSurface },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  bell: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center" },
  bellDark: { backgroundColor: "rgba(255,255,255,0.22)" },
  bellFloat: { position: "absolute", right: spacing.lg },
  bellBadge: { position: "absolute", top: 2, right: 2, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.error, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  bellBadgeText: { color: "#FFFFFF", fontSize: 10, fontWeight: "800" },
  statusCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl, alignItems: "center", gap: spacing.sm },
  statusTitle: { fontSize: 22, fontWeight: "700", textAlign: "center" },
  statusBody: { color: colors.onSurfaceSecondary, fontSize: 14, lineHeight: 20, textAlign: "center" },
  statusCta: { borderRadius: radius.pill, overflow: "hidden", marginTop: spacing.md, alignSelf: "stretch" },
  statusCtaBg: { paddingVertical: 15, alignItems: "center" },
  statusCtaText: { color: "#FFFFFF", fontWeight: "700", fontSize: 15 },
  header: { height: 200, padding: spacing.lg, overflow: "hidden", justifyContent: "flex-end", gap: 6 },
  approvedBadge: { alignSelf: "flex-start", backgroundColor: colors.success, paddingHorizontal: spacing.md, paddingVertical: 4, borderRadius: radius.pill },
  approvedText: { color: "#FFFFFF", fontSize: 10, fontWeight: "800", letterSpacing: 0.8 },
  shopName: { color: "#FFFFFF", fontSize: 30, fontWeight: "300", fontStyle: "italic" },
  shopLoc: { color: "rgba(255,255,255,0.9)", fontSize: 13 },
  metricGrid: { flexDirection: "row", flexWrap: "wrap", padding: spacing.lg, gap: spacing.md },
  metric: { width: (width - spacing.lg * 2 - spacing.md) / 2, backgroundColor: colors.surfaceSecondary, padding: spacing.md, borderRadius: radius.md, gap: 4 },
  metricNum: { fontSize: 22, fontWeight: "700", color: colors.brandPrimary },
  metricLabel: { fontSize: 12, color: colors.muted, fontWeight: "600" },
  quickRow: { flexDirection: "row", paddingHorizontal: spacing.lg, gap: spacing.sm },
  quick: { flex: 1, padding: spacing.md, alignItems: "center", backgroundColor: colors.brandTertiary, borderRadius: radius.md, gap: 6 },
  quickLabel: { color: colors.onBrandTertiary, fontSize: 12, fontWeight: "700" },
  sectionTitle: { fontSize: 18, fontWeight: "700", color: colors.onSurface, paddingHorizontal: spacing.lg, marginTop: spacing.lg, marginBottom: spacing.sm },
  orderRow: { flexDirection: "row", alignItems: "center", padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md },
  orderNo: { fontWeight: "700", color: colors.onSurface, fontSize: 14 },
  orderCust: { color: colors.muted, fontSize: 12, marginTop: 2 },
  orderPrice: { color: colors.brandPrimary, fontWeight: "700", fontSize: 15 },
  payTag: { fontSize: 10, fontWeight: "800", marginTop: 2 },
  notifHead: { fontSize: 16, fontWeight: "700", color: colors.onSurface, marginTop: spacing.md },
  notifHeadRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end" },
  seeAll: { color: colors.brandPrimary, fontWeight: "700", fontSize: 13, marginBottom: 2 },
  lowCard: { marginHorizontal: spacing.lg, marginTop: spacing.lg, backgroundColor: colors.warning + "12", borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.warning + "44", gap: 6 },
  lowHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  lowTitle: { fontSize: 15, fontWeight: "800", color: colors.warning },
  lowManage: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  lowSub: { fontSize: 12, color: colors.onSurfaceSecondary, marginBottom: 4 },
  lowRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 4 },
  lowImg: { width: 34, height: 34, borderRadius: radius.sm, backgroundColor: colors.surfaceTertiary },
  lowName: { flex: 1, fontSize: 13, fontWeight: "600", color: colors.onSurface },
  lowBadge: { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.pill },
  lowBadgeText: { color: "#FFFFFF", fontSize: 10, fontWeight: "800" },
  lowMore: { fontSize: 12, color: colors.muted, marginTop: 2 },
  notif: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md },
  notifUnread: { borderLeftWidth: 3, borderLeftColor: colors.brandPrimary },
  notifTitle: { fontWeight: "700", color: colors.onSurface, fontSize: 13 },
  notifBody: { color: colors.muted, fontSize: 12, marginTop: 2 },
});
