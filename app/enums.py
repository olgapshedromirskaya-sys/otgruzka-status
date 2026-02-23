from enum import Enum

class Marketplace(str, Enum):
    WB = "wb"
    OZON = "ozon"

class OrderStatus(str, Enum):
    NEW = "new"
    ASSEMBLY = "assembly"
    TRANSFERRED_TO_DELIVERY = "transferred_to_delivery"
    ACCEPTED_AT_WAREHOUSE = "accepted_at_warehouse"
    IN_TRANSIT_TO_BUYER = "in_transit_to_buyer"
    ARRIVED_AT_BUYER_PICKUP = "arrived_at_buyer_pickup"
    BUYOUT = "buyout"
    RETURN_STARTED = "return_started"
    REJECTION = "rejection"
    DEFECT = "defect"
    RETURN_IN_TRANSIT_FROM_BUYER = "return_in_transit_from_buyer"
    RETURN_ARRIVED_TO_SELLER_PICKUP = "return_arrived_to_seller_pickup"
    SELLER_PICKED_UP = "seller_picked_up"

MARKETPLACE_LABELS = {
    Marketplace.WB: "Wildberries",
    Marketplace.OZON: "Ozon",
}

STATUS_LABELS = {
    OrderStatus.NEW: "Новый заказ",
    OrderStatus.ASSEMBLY: "Заказ на сборке",
    OrderStatus.TRANSFERRED_TO_DELIVERY: "Передан в доставку",
    OrderStatus.ACCEPTED_AT_WAREHOUSE: "Принят на складе",
    OrderStatus.IN_TRANSIT_TO_BUYER: "Товар в пути к покупателю",
    OrderStatus.ARRIVED_AT_BUYER_PICKUP: "Прибыл на ПВЗ покупателя",
    OrderStatus.BUYOUT: "Выкупили",
    OrderStatus.RETURN_STARTED: "Возврат",
    OrderStatus.REJECTION: "Покупатель отказался от товара",
    OrderStatus.DEFECT: "Возврат вернули как брак",
    OrderStatus.RETURN_IN_TRANSIT_FROM_BUYER: "Возврат в пути от покупателя",
    OrderStatus.RETURN_ARRIVED_TO_SELLER_PICKUP: "Возврат прибыл на ПВЗ продавца",
    OrderStatus.SELLER_PICKED_UP: "Продавец товар забрал",
}

FINAL_STATUSES = {
    OrderStatus.BUYOUT,
    OrderStatus.REJECTION,
    OrderStatus.DEFECT,
    OrderStatus.SELLER_PICKED_UP,
}
