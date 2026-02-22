from enum import Enum


class Marketplace(str, Enum):
    WB = "wb"
    OZON = "ozon"


class OrderStatus(str, Enum):
    ASSEMBLY = "assembly"
    WAREHOUSE_HANDOVER = "warehouse_handover"
    SORTED = "sorted"
    IN_TRANSIT_TO_BUYER_PICKUP = "in_transit_to_buyer_pickup"
    ARRIVED_AT_BUYER_PICKUP = "arrived_at_buyer_pickup"
    BUYOUT = "buyout"
    REJECTION = "rejection"
    RETURN_STARTED = "return_started"
    DEFECT = "defect"
    RETURN_IN_TRANSIT_FROM_BUYER = "return_in_transit_from_buyer"
    RETURN_ARRIVED_TO_SELLER_PICKUP = "return_arrived_to_seller_pickup"


MARKETPLACE_LABELS = {
    Marketplace.WB: "Wildberries",
    Marketplace.OZON: "Ozon",
}

STATUS_LABELS = {
    OrderStatus.ASSEMBLY: "Сборка",
    OrderStatus.WAREHOUSE_HANDOVER: "Сдача на склад маркетплейса",
    OrderStatus.SORTED: "Прошел сортировку",
    OrderStatus.IN_TRANSIT_TO_BUYER_PICKUP: "В пути на ПВЗ покупателя",
    OrderStatus.ARRIVED_AT_BUYER_PICKUP: "Прибыл на ПВЗ покупателя",
    OrderStatus.BUYOUT: "Выкуп",
    OrderStatus.REJECTION: "Отказ",
    OrderStatus.RETURN_STARTED: "Возврат",
    OrderStatus.DEFECT: "Брак",
    OrderStatus.RETURN_IN_TRANSIT_FROM_BUYER: "Возврат в пути от покупателя",
    OrderStatus.RETURN_ARRIVED_TO_SELLER_PICKUP: "Возврат прибыл на ПВЗ продавца",
}

FINAL_STATUSES = {
    OrderStatus.BUYOUT,
    OrderStatus.REJECTION,
    OrderStatus.DEFECT,
    OrderStatus.RETURN_ARRIVED_TO_SELLER_PICKUP,
}

