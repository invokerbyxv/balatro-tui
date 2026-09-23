class ScoreCalculator:
    def __init__(self, hand_stats, jokers=[], enhancements=[], vouchers=[]):
        self.hand_stats = hand_stats or {"chips": 0, "mult": 0}
        self.jokers = jokers
        self.enhancements = enhancements
        self.vouchers = vouchers
    
    def calculate(self):
        base_chips = self.hand_stats.get("chips", 0)
        base_mult = self.hand_stats.get("mult", 1)
        
        joker_mult = 1
        joker_chips = 0
        
        for joker in self.jokers:
            joker_effect = joker.get("effect", "")
            config = joker.get("config", {})
            
            if joker_effect == "Mult" and "mult" in config:
                joker_mult += config["mult"]
            elif joker_effect == "Suit Mult" and "extra" in config:
                extra = config["extra"]
                if "s_mult" in extra:
                    joker_mult *= (1 + extra["s_mult"])
            elif joker_effect == "Type Mult" and "t_mult" in config:
                joker_mult += config["t_mult"]
            elif joker_effect == "Type Chips" and "t_chips" in config:
                joker_chips += config["t_chips"]
            elif joker_effect == "Hand Size Mult" and "extra" in config:
                extra = config["extra"]
                if "mult" in extra and "size" in extra:
                    hand_size = len(self.hand_stats.get("cards", []))
                    if hand_size >= extra["size"]:
                        joker_mult *= extra["mult"]
            elif joker_effect == "Discard Chips" and "extra" in config:
                joker_chips += config["extra"]
            elif joker_effect == "No Discard Mult" and "extra" in config:
                extra = config["extra"]
                if "mult" in extra and extra.get("d_remaining") == 0:
                    joker_mult *= extra["mult"]
            elif joker_effect == "1 in 10 mult" and "extra" in config:
                extra = config["extra"]
                if "Xmult" in extra and "every" in extra:
                    total_discards = self.hand_stats.get("total_discards", 0)
                    if total_discards % extra["every"] == 0:
                        joker_mult *= extra["Xmult"]
            elif joker_effect == "Random Mult" and "extra" in config:
                import random
                extra = config["extra"]
                min_mult = extra.get("min", 0)
                max_mult = extra.get("max", 10)
                joker_mult *= (min_mult + random.randint(0, max_mult - min_mult))
            elif joker_effect == "Bonus Rerolls" and "extra" in config:
                pass
        
        enhancement_mult = 1
        for enh in self.enhancements:
            if enh.get("type") == "mult":
                enhancement_mult *= (1 + enh.get("value", 0))
        
        voucher_mult = 1
        voucher_chips = 0
        
        for voucher in self.vouchers:
            effect = voucher.get("effect", "")
            config = voucher.get("config", {})
            
            if effect == "Mult on first hand each round":
                if self.hand_stats.get("is_first_hand", True):
                    voucher_mult *= (1 + config.get("mult", 4))
            elif effect == "+$1 at start of each shop":
                pass
            elif effect.endswith(" cards have +1 chip"):
                suit_config = config.get("suit", "")
                chips_config = config.get("chips", 1)
                cards = self.hand_stats.get("cards", [])
                matching_cards = sum(1 for c in cards if c.get("suit") == suit_config)
                voucher_chips += matching_cards * chips_config
            elif effect.endswith(" cards have +1 mult"):
                suit_config = config.get("suit", "")
                mult_config = config.get("mult", 1)
                cards = self.hand_stats.get("cards", [])
                matching_cards = sum(1 for c in cards if c.get("suit") == suit_config)
                voucher_mult += matching_cards * mult_config
        
        total_chips = (base_chips + joker_chips + voucher_chips) * joker_mult
        total_mult = base_mult * joker_mult * enhancement_mult * voucher_mult
        
        final_score = total_chips * total_mult
        
        return {
            "base_chips": base_chips,
            "base_mult": base_mult,
            "joker_mult": joker_mult,
            "enhancement_mult": enhancement_mult,
            "voucher_mult": voucher_mult,
            "final_chips": total_chips,
            "final_mult": total_mult,
            "final_score": final_score
        }
