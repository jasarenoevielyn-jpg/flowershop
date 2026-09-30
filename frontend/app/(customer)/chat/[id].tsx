import { useLocalSearchParams } from "expo-router";
import OrderChat from "@/src/components/OrderChat";

export default function CustomerChat() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <OrderChat orderId={id} />;
}
