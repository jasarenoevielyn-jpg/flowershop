import { useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, TextInput, FlatList, ActivityIndicator, Platform } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { colors, spacing, radius } from "@/src/theme";
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";

/**
 * Shared per-order chat used by both the customer and the shop owner. The
 * backend authorizes access by the caller's token, so the same component works
 * for both roles — messages the current user sent are right-aligned.
 */
export default function OrderChat({ orderId }: { orderId: string }) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { user } = useAuth();
  const [text, setText] = useState("");
  const inputRef = useRef<TextInput>(null);

  const { data: order } = useQuery({ queryKey: ["chat-order", orderId], queryFn: () => api(`/orders/${orderId}`), enabled: !!orderId });
  const { data: messages = [], isLoading } = useQuery({
    queryKey: ["messages", orderId],
    queryFn: () => api(`/orders/${orderId}/messages`),
    enabled: !!orderId,
    refetchInterval: 4000,
  });

  const send = useMutation({
    mutationFn: (t: string) => api(`/orders/${orderId}/messages`, { method: "POST", body: JSON.stringify({ text: t }) }),
    onSuccess: () => { setText(""); qc.invalidateQueries({ queryKey: ["messages", orderId] }); },
  });

  const onSend = () => {
    const t = text.trim();
    if (!t || send.isPending) return;
    send.mutate(t);
  };

  const isOwner = user?.role === "flower_owner";
  const peer = isOwner ? (order?.contact_name || order?.customer_name || "Customer") : "Flower Shop";
  const reversed = [...messages].reverse();

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }} testID="order-chat">
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="chat-back-btn" onPress={() => router.back()} hitSlop={8}><Text style={styles.back}>←</Text></Pressable>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.title} numberOfLines={1}>{peer}</Text>
          <Text style={styles.sub}>Order {order?.order_no || ""}</Text>
        </View>
        <View style={{ width: 24 }} />
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior="translate-with-padding" keyboardVerticalOffset={0}>
        {isLoading ? (
          <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
        ) : (
          <FlatList
            data={reversed}
            inverted
            keyExtractor={(m: any) => m.id}
            contentContainerStyle={{ padding: spacing.lg, gap: spacing.sm, flexGrow: 1 }}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive"
            renderItem={({ item }) => {
              const mine = item.sender_id === user?.id;
              return (
                <View style={[styles.bubbleRow, mine ? styles.rowMine : styles.rowTheirs]} testID={`msg-${item.id}`}>
                  <View style={[styles.bubble, mine ? styles.bubbleMine : styles.bubbleTheirs]}>
                    {!mine && <Text style={styles.senderName}>{item.sender_name}</Text>}
                    <Text style={[styles.msgText, mine && { color: colors.onBrandPrimary }]}>{item.text}</Text>
                  </View>
                </View>
              );
            }}
            ListEmptyComponent={
              <View style={styles.empty}>
                <Text style={styles.emptyEmoji}>💬</Text>
                <Text style={styles.emptyText}>No messages yet.{"\n"}Ask about your order or delivery here.</Text>
              </View>
            }
          />
        )}

        <View style={[styles.inputBar, { paddingBottom: insets.bottom + spacing.sm }]}>
          <TextInput
            ref={inputRef}
            testID="chat-input"
            value={text}
            onChangeText={setText}
            placeholder="Type a message..."
            placeholderTextColor={colors.muted}
            style={styles.input}
            multiline
            onSubmitEditing={onSend}
          />
          <Pressable testID="chat-send-btn" onPress={onSend} disabled={!text.trim() || send.isPending} style={[styles.sendBtn, (!text.trim() || send.isPending) && { opacity: 0.5 }]}>
            <Text style={styles.sendText}>{send.isPending ? "…" : "➤"}</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider },
  back: { fontSize: 22, color: colors.onSurface },
  title: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.muted, marginTop: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  bubbleRow: { flexDirection: "row" },
  rowMine: { justifyContent: "flex-end" },
  rowTheirs: { justifyContent: "flex-start" },
  bubble: { maxWidth: "80%", paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.lg },
  bubbleMine: { backgroundColor: colors.brandPrimary, borderBottomRightRadius: radius.sm },
  bubbleTheirs: { backgroundColor: colors.surfaceSecondary, borderBottomLeftRadius: radius.sm },
  senderName: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary, marginBottom: 2 },
  msgText: { fontSize: 14, color: colors.onSurface, lineHeight: 19 },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", transform: [{ scaleY: -1 }], paddingTop: spacing.xxl },
  emptyEmoji: { fontSize: 40, marginBottom: spacing.sm },
  emptyText: { color: colors.muted, textAlign: "center", fontSize: 13, lineHeight: 19 },
  inputBar: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.md, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider, backgroundColor: colors.surface },
  input: { flex: 1, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, paddingHorizontal: spacing.md, paddingTop: 10, paddingBottom: 10, fontSize: 14, color: colors.onSurface, maxHeight: 120 },
  sendBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  sendText: { color: colors.onBrandPrimary, fontSize: 18, fontWeight: "800" },
});
