import { View, Text, StyleSheet, Pressable, FlatList, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { colors, spacing, radius } from "@/src/theme";
import { api } from "@/src/api";

const KIND_META: Record<string, { emoji: string; tint: string }> = {
  chat: { emoji: "💬", tint: colors.info },
  payment: { emoji: "💳", tint: colors.success },
  order: { emoji: "📦", tint: colors.brandPrimary },
  stock: { emoji: "⚠️", tint: colors.warning },
  application: { emoji: "🏪", tint: colors.brandSecondary },
  review: { emoji: "⭐", tint: colors.warning },
  info: { emoji: "🔔", tint: colors.muted },
};

function ago(iso?: string) {
  if (!iso) return "";
  try { return formatDistanceToNow(new Date(iso), { addSuffix: true }); } catch { return ""; }
}

export default function OwnerInbox() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: notifs = [], isLoading } = useQuery({ queryKey: ["owner-notifs"], queryFn: () => api("/notifications"), refetchInterval: 6000 });

  const readOne = useMutation({
    mutationFn: (nid: string) => api(`/notifications/${nid}/read`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["owner-notifs"] }),
  });
  const readAll = useMutation({
    mutationFn: () => api("/notifications/read-all", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["owner-notifs"] }),
  });

  const unread = notifs.filter((n: any) => !n.read).length;

  const openNotif = (n: any) => {
    if (!n.read) readOne.mutate(n.id);
    if (n.kind === "chat" && n.order_id) router.push(`/(owner)/chat/${n.order_id}` as any);
    else if (n.order_id) router.push(`/(owner)/order/${n.order_id}` as any);
    else if (n.kind === "stock") router.push("/(owner)/products");
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="inbox-back-btn" onPress={() => router.back()} hitSlop={8}><Text style={styles.back}>←</Text></Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Updates</Text>
          <Text style={styles.sub}>{unread > 0 ? `${unread} unread` : "All caught up 🌸"}</Text>
        </View>
        {unread > 0 && (
          <Pressable testID="mark-all-read-btn" onPress={() => readAll.mutate()} hitSlop={8}>
            <Text style={styles.markAll}>Mark all read</Text>
          </Pressable>
        )}
      </View>

      {isLoading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : (
        <FlatList
          data={notifs}
          keyExtractor={(n: any) => n.id}
          contentContainerStyle={{ padding: spacing.lg, gap: spacing.sm, paddingBottom: 100 }}
          renderItem={({ item }) => {
            const meta = KIND_META[item.kind] || KIND_META.info;
            return (
              <Pressable testID={`inbox-notif-${item.id}`} onPress={() => openNotif(item)} style={[styles.row, !item.read && styles.rowUnread]}>
                <View style={[styles.iconWrap, { backgroundColor: meta.tint + "22" }]}>
                  <Text style={{ fontSize: 18 }}>{meta.emoji}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle} numberOfLines={1}>{item.title}</Text>
                  <Text style={styles.rowBody} numberOfLines={2}>{item.body}</Text>
                  <Text style={styles.rowTime}>{ago(item.created_at)}</Text>
                </View>
                {!item.read && <View style={styles.dot} />}
              </Pressable>
            );
          }}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={{ fontSize: 44 }}>🔔</Text>
              <Text style={styles.emptyText}>No updates yet.{"\n"}New messages, paid orders and stock alerts will show here.</Text>
            </View>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider },
  back: { fontSize: 22, color: colors.onSurface },
  title: { fontSize: 22, fontWeight: "300", fontStyle: "italic", color: colors.onSurface },
  sub: { color: colors.muted, fontSize: 12, marginTop: 1 },
  markAll: { color: colors.brandPrimary, fontWeight: "700", fontSize: 13 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.divider },
  rowUnread: { backgroundColor: colors.surfaceSecondary, borderColor: colors.borderStrong },
  iconWrap: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  rowTitle: { fontWeight: "700", color: colors.onSurface, fontSize: 14 },
  rowBody: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2, lineHeight: 17 },
  rowTime: { color: colors.muted, fontSize: 11, marginTop: 4 },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.brandPrimary },
  empty: { alignItems: "center", justifyContent: "center", marginTop: 80, gap: spacing.md, paddingHorizontal: spacing.xl },
  emptyText: { color: colors.muted, textAlign: "center", fontSize: 13, lineHeight: 19 },
});
