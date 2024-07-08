from collections import defaultdict
from django.db.models.query import QuerySet
from django.db.models import Case, When, IntegerField
import math

class SyllableSearch:
    CHAR_OFFSET = 44032  # Unicode '가'
    CONSONANTS = 588 # 초성
    VOWELS = 28 # 중성
    JONG_SUNG = 28
    BIT_LENGTH_PER_TYPE = 10  # Example: 3 bits for each syllable type

    CHO_BITS = math.ceil(math.log2(588))  # 10 bits
    JUNG_BITS = math.ceil(math.log2(28))  # 5 bits
    JONG_BITS = math.ceil(math.log2(28))  # 5 bits

    CHO_BIT_POS = 0
    JUNG_BIT_POS = CHO_BITS
    JONG_BIT_POS = CHO_BITS + JUNG_BITS

    @staticmethod
    def decompose_syllables(text):
        def decompose_char(char):
            if '가' <= char <= '힣':
                char_code = ord(char) - SyllableSearch.CHAR_OFFSET
                jong_sung = char_code % SyllableSearch.JONG_SUNG
                jung_sung = ((char_code - jong_sung) // SyllableSearch.JONG_SUNG) % SyllableSearch.VOWELS
                cho_sung = ((char_code - jong_sung) // SyllableSearch.JONG_SUNG) // SyllableSearch.VOWELS
                return (cho_sung, jung_sung, jong_sung if jong_sung > 0 else None)
            elif 'ㄱ' <= char <= 'ㅎ' or 'ㅏ' <= char <= 'ㅣ':  # If the character is a consonant or vowel
                return (ord(char) - ord('ㄱ'),)  # Treat it as a separate syllable
            else:
                return None
        return [decompose_char(char) for char in text if decompose_char(char) is not None]
    
    @staticmethod
    def generate_syllable_combinations(syllables):
        combinations = []
        for syllable in syllables:
            if len(syllable) == 1:  # If the syllable is a single consonant or vowel
                combinations.append(syllable)  # Treat it as a separate combination
            else:
                cho, jung, jong = syllable
                if cho is not None and jung is not None:
                    combinations.append((cho, jung))
                if jung is not None and jong is not None:
                    combinations.append((jung, jong))
                if jong is not None and cho is not None:
                    combinations.append((jong, cho))
        return combinations
    
    @staticmethod
    def convert_combos_to_binary(combos):
        bitmask = 0
        for combo in combos:
            if len(combo) == 1:  # If the combo is a single consonant or vowel
                cho = combo[0]
                bitmask |= 1 << (SyllableSearch.CHO_BIT_POS + cho)
            else:  # If the combo is a syllable
                cho, jung = combo
                if cho is not None:
                    bitmask |= 1 << (SyllableSearch.CHO_BIT_POS + cho)
                if jung is not None:
                    bitmask |= 1 << (SyllableSearch.JUNG_BIT_POS + jung)
        return bitmask

    @staticmethod
    def calculate_score(search_term_binary, qs_binary):
        # Convert memoryview to bytes, then to int
        qs_binary_int = int.from_bytes(qs_binary, 'big')
        # Calculate the score as the sum of the weights of the matching bits
        score = 0
        match_bits = search_term_binary & qs_binary_int
        while match_bits:
            bit_pos = match_bits.bit_length() - 1
            if bit_pos >= SyllableSearch.JUNG_BIT_POS:
                score += 2  # Weight for jung
            else:
                score += 3  # Weight for cho
            match_bits &= match_bits - 1  # Clear the rightmost set bit
        return score

    
    @staticmethod
    def syllable_search(search_term: str, queryset: QuerySet) -> QuerySet:
        search_term_syllables = SyllableSearch.decompose_syllables(search_term)
        search_term_combos = SyllableSearch.generate_syllable_combinations(search_term_syllables)
        search_term_binary = SyllableSearch.convert_combos_to_binary(search_term_combos)

        qs_scores = defaultdict(int)
        for qs in queryset:
            score = 0 if not hasattr(qs, 'precomputed_combo_bits') else SyllableSearch.calculate_score(search_term_binary, qs.precomputed_combo_bits)
            print("Score: ", score, " title ", qs.title)
            qs_scores[qs.id] = score

        # Find the highest score
        highest_score = max(qs_scores.values()) if qs_scores else 0
        # Calculate the threshold as 70% of the highest score
        threshold_score = highest_score * 0.65

        filtered_qs_ids = [id for id, score in qs_scores.items() if score >= threshold_score]
        filtered_qs_ids.sort(key=lambda id: qs_scores[id], reverse=True)

        preserved_order = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(filtered_qs_ids)], output_field=IntegerField())
        filtered_queryset = queryset.filter(id__in=filtered_qs_ids).order_by(preserved_order)

        return filtered_queryset