import { useLocalSearchParams } from "expo-router";
import OrderChat from "@/src/components/OrderChat";

export default function OwnerChat() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <OrderChat orderId={id} />;
}
