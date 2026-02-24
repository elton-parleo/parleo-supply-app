import re

class DataTransformer:
    @staticmethod
    def parse_price_and_currency(price_str):
        """
        Extracts currency symbol and converts numeric part to integer cents.
        Example: '$58.00' -> (5800, 'USD') or '$'
        """
        if not price_str or price_str.lower() == "null":
            return None, None
        
        # Extract the numeric part (digits and decimal)
        numeric_match = re.search(r'[\d.]+', price_str)
        # Extract the currency symbol (anything that isn't a digit, dot, or space)
        currency_match = re.search(r'[^\d.\s]+', price_str)
        
        price_val = None
        currency_val = currency_match.group(0) if currency_match else "USD" # Default to USD if symbol missing

        if numeric_match:
            try:
                # Converting to cents (Integer)
                price_val = int(float(numeric_match.group(0)) * 100)
            except ValueError:
                price_val = None
                
        return price_val, currency_val

    @staticmethod
    def parse_review_count(review_val):
        """
        Converts review counts (int or string) to integers.
        Handles shorthand like '1.3k' -> 1300 or '2M' -> 2000000.
        """
        if review_val is None or str(review_val).lower() == "null":
            return 0
        
        if isinstance(review_val, int):
            return review_val
        
        # Clean string: lowercase and remove commas/whitespace
        clean_val = str(review_val).lower().replace(',', '').strip()
        
        multipliers = {
            'k': 1000,
            'm': 1000000
        }
        
        # Check for suffix
        for suffix, multiplier in multipliers.items():
            if clean_val.endswith(suffix):
                try:
                    number_part = float(clean_val.replace(suffix, ''))
                    return int(number_part * multiplier)
                except ValueError:
                    return 0
                    
        # Default numeric conversion
        try:
            return int(float(clean_val))
        except ValueError:
            return 0
        
    def transform_item(self, item, currency="USD"):
        """Maps raw JSON dictionary to a clean dictionary."""
        price, currency = self.parse_price_and_currency(item.get("price"))
        value, _ = self.parse_price_and_currency(item.get("value"))
        sale, _ = self.parse_price_and_currency(item.get("sale_price"))
        
        return {
            "sku": str(item.get("sku")),
            "brand": item.get("brand"),
            "title": item.get("title"),
            "category": item.get("category"),
            "star_review": item.get("star_review"),
            "number_of_reviews": self.parse_review_count(item.get("number_of_reviews")),
            "price": price,
            "value": value,
            "sale_price": sale,
            "currency": currency,
            "link": item.get("link"),
            "image_link": item.get("image_link")
        }