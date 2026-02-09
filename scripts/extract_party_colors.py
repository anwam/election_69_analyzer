#!/usr/bin/env python3
"""
Extract dominant colors from party icon images and update party-data.json
This script runs ONCE to map party icons to their brand colors.
Features:
- Extracts primary and secondary colors from party icons
- Merges colors if no clear dominant color exists
- Ensures colors are distinct from other parties
"""

import json
import os
import sys
from collections import Counter
from colorsys import hsv_to_rgb, rgb_to_hsv
from pathlib import Path

# Configuration
PARTY_DATA_FILE = "docs/data/party-data.json"
PARTY_ICONS_DIR = "docs/img"
OUTPUT_FILE = "docs/data/party-data.json"  # Overwrite the same file

# Color similarity threshold (0-1, lower = more strict)
# Delta E in RGB space - roughly 30-40 is visually similar
COLOR_SIMILARITY_THRESHOLD = 35


def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    """Convert RGB tuple to hex color."""
    return f"#{int(rgb[0]):02X}{int(rgb[1]):02X}{int(rgb[2]):02X}"


def color_distance(rgb1, rgb2):
    """
    Calculate Euclidean distance between two RGB colors.
    Lower value = more similar.
    """
    return sum((a - b) ** 2 for a, b in zip(rgb1, rgb2)) ** 0.5


def is_too_light_or_dark_or_gray(hex_color):
    """
    Check if a color is too close to white, black, or gray.
    Returns True if the color should be excluded.
    """
    # Remove # if present
    hex_color = hex_color.lstrip("#")

    # Convert to RGB
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Calculate perceived brightness (human eye weights colors differently)
    # Using the formula: 0.299*R + 0.587*G + 0.114*B
    brightness = 0.299 * r + 0.587 * g + 0.114 * b

    # Also check saturation (colorfulness) to avoid grays
    max_val = max(r, g, b)
    min_val = min(r, g, b)
    saturation = (max_val - min_val) / max_val if max_val > 0 else 0

    # Exclude colors that are:
    # - Too dark (< 60) or too light (> 235) - stricter threshold
    # - Too gray/unsaturated (< 0.15) - avoids white, gray, black, and washed-out colors
    return brightness < 60 or brightness > 235 or saturation < 0.15


def merge_colors(rgb1, rgb2, ratio=0.5):
    """
    Merge two colors together.
    ratio: 0.5 = equal mix, 0.7 = 70% color1, 30% color2
    """
    return (
        rgb1[0] * ratio + rgb2[0] * (1 - ratio),
        rgb1[1] * ratio + rgb2[1] * (1 - ratio),
        rgb1[2] * ratio + rgb2[2] * (1 - ratio),
    )


def is_dominant_color(color_counter, dominant_rgb):
    """
    Check if the dominant color is truly dominant (clear winner).
    Returns True if the top color has significantly more votes than the second.
    """
    if len(color_counter) < 2:
        return True  # Only one color found

    top_count = color_counter[dominant_rgb]
    second_rgb, second_count = color_counter.most_common(2)[1]

    # Check if dominant color has at least 30% more occurrences
    return top_count >= second_count * 1.3


def extract_colors_from_image(image_path, existing_colors=None):
    """
    Extract the dominant and secondary colors from an image file.
    Returns hex color string or None if extraction fails.

    existing_colors: dict of {party_code: hex_color} to check for similarity
    """
    try:
        from PIL import Image

        img = Image.open(image_path)

        # Convert to RGB if necessary
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Resize to small size for faster processing
        img_small = img.resize((50, 50), Image.Resampling.LANCZOS)

        # Get all pixels
        pixels = list(img_small.getdata())

        # Filter out colors that are too light or dark (white/black backgrounds)
        filtered_pixels = []
        for r, g, b in pixels:
            brightness = 0.299 * r + 0.587 * g + 0.114 * b
            if 50 <= brightness <= 245:  # Exclude very dark and very light
                filtered_pixels.append((r, g, b))

        # If no valid pixels found, use all pixels
        if not filtered_pixels:
            filtered_pixels = pixels

        # Count color occurrences (with some tolerance for similar colors)
        # Round RGB values to nearest 10 to group similar colors
        rounded_pixels = []
        for r, g, b in filtered_pixels:
            r = round(r / 10) * 10
            g = round(g / 10) * 10
            b = round(b / 10) * 10
            rounded_pixels.append((r, g, b))

        color_counter = Counter(rounded_pixels)

        if not color_counter:
            return None

        # Get top colors
        top_colors = color_counter.most_common(5)
        dominant_rgb = top_colors[0][0]
        dominant_hex = rgb_to_hex(dominant_rgb)

        # Check if dominant color is valid (not too light/dark/gray)
        if is_too_light_or_dark_or_gray(dominant_hex):
            # Try secondary colors
            for rgb, _ in top_colors[1:]:
                test_hex = rgb_to_hex(rgb)
                if not is_too_light_or_dark_or_gray(test_hex):
                    dominant_rgb = rgb
                    dominant_hex = test_hex
                    break
            else:
                # All top colors are invalid, try merging
                if len(top_colors) >= 2:
                    merged_rgb = merge_colors(top_colors[0][0], top_colors[1][0])
                    merged_hex = rgb_to_hex(merged_rgb)
                    if not is_too_light_or_dark_or_gray(merged_hex):
                        dominant_rgb = merged_rgb
                        dominant_hex = merged_hex
                    else:
                        return None
                else:
                    return None

        # Check if dominant color is truly dominant
        is_clear_dominant = is_dominant_color(color_counter, dominant_rgb)

        # Check for similarity with existing party colors
        if existing_colors:
            dominant_rgb = hex_to_rgb(dominant_hex)
            for other_party, other_hex in existing_colors.items():
                other_rgb = hex_to_rgb(other_hex)
                distance = color_distance(dominant_rgb, other_rgb)
                if distance < COLOR_SIMILARITY_THRESHOLD:
                    # Colors are too similar - merge with secondary color to differentiate
                    if len(top_colors) >= 2:
                        secondary_rgb = top_colors[1][0]
                        # Merge 60% dominant with 40% secondary
                        new_rgb = merge_colors(dominant_rgb, secondary_rgb, 0.6)
                        new_hex = rgb_to_hex(new_rgb)

                        # Verify merged color is still valid
                        if not is_too_light_or_dark_or_gray(new_hex):
                            dominant_rgb = new_rgb
                            dominant_hex = new_hex
                    break

        # If not clearly dominant, merge with secondary color for better representation
        if not is_clear_dominant and len(top_colors) >= 2:
            secondary_rgb = top_colors[1][0]
            # Merge 50-50 for blended look
            blended_rgb = merge_colors(dominant_rgb, secondary_rgb, 0.5)
            blended_hex = rgb_to_hex(blended_rgb)

            # Only use blended if it's valid
            if not is_too_light_or_dark_or_gray(blended_hex):
                dominant_hex = blended_hex

        return dominant_hex

    except ImportError:
        print("Warning: PIL/Pillow not installed. Install with: pip install Pillow")
        print("Falling back to basic color extraction...")
        return None
    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return None


def main():
    print("=" * 60)
    print("Party Color Extraction Tool v2")
    print("Features: Dominant color detection + Secondary color merge")
    print("=" * 60)

    # Load existing party data
    if not os.path.exists(PARTY_DATA_FILE):
        print(f"Error: Party data file not found: {PARTY_DATA_FILE}")
        sys.exit(1)

    with open(PARTY_DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    parties = data.get("parties", [])
    print(f"\nFound {len(parties)} parties in data file")

    # Count for stats
    updated_count = 0
    skipped_count = 0
    error_count = 0
    merged_count = 0

    # Track colors assigned so far (for similarity checking)
    assigned_colors = {}

    # First pass: collect all icons and extract colors
    party_data = []
    for party in parties:
        party_code = party.get("code")
        party_name = party.get("name", "Unknown")
        old_color = party.get("colorPrimary", "N/A")

        if not party_code:
            continue

        # Look for the icon file
        icon_path = None
        for ext in [".webp", ".png", ".jpg"]:
            test_path = os.path.join(PARTY_ICONS_DIR, f"{party_code}{ext}")
            if os.path.exists(test_path):
                icon_path = test_path
                break

        party_data.append(
            {
                "code": party_code,
                "name": party_name,
                "old_color": old_color,
                "icon_path": icon_path,
                "party_ref": party,
            }
        )

    # Process in order (to maintain consistency)
    for pd in party_data:
        party_code = pd["code"]
        party_name = pd["name"]
        old_color = pd["old_color"]
        icon_path = pd["icon_path"]
        party_ref = pd["party_ref"]

        if not icon_path:
            print(f"  ⚠️  {party_code} ({party_name}): No icon found")
            skipped_count += 1
            # Keep old color if exists, otherwise skip
            if old_color != "N/A":
                assigned_colors[party_code] = old_color
            continue

        # Extract color with similarity check against already assigned colors
        extracted_color = extract_colors_from_image(icon_path, assigned_colors)

        if extracted_color:
            party_ref["colorPrimary"] = extracted_color
            assigned_colors[party_code] = extracted_color

            # Check if this was a merge operation
            if len(extract_colors_from_image.__code__.co_varnames) > 0:
                pass  # Internal tracking

            status_symbol = "✓"
            note = ""

            # Detect if color is likely a merge (secondary was used)
            # by checking if it differs from simple dominant extraction
            from PIL import Image

            try:
                img = Image.open(icon_path)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img_small = img.resize((50, 50), Image.Resampling.LANCZOS)
                pixels = list(img_small.getdata())

                filtered_pixels = []
                for r, g, b in pixels:
                    brightness = 0.299 * r + 0.587 * g + 0.114 * b
                    if 50 <= brightness <= 245:
                        filtered_pixels.append((r, g, b))

                if not filtered_pixels:
                    filtered_pixels = pixels

                rounded_pixels = []
                for r, g, b in filtered_pixels:
                    r = round(r / 10) * 10
                    g = round(g / 10) * 10
                    b = round(b / 10) * 10
                    rounded_pixels.append((r, g, b))

                color_counter = Counter(rounded_pixels)

                # Simple dominant extraction
                if color_counter:
                    simple_rgb = color_counter.most_common(1)[0][0]
                    simple_hex = rgb_to_hex(simple_rgb)

                    # If extracted differs from simple, it was merged/adjusted
                    if extracted_color != simple_hex and not is_too_light_or_dark_or_gray(
                        simple_hex
                    ):
                        note = " (merged)"
                        merged_count += 1
            except:
                pass

            print(
                f"  {status_symbol} {party_code} ({party_name}): {old_color} → {extracted_color}{note}"
            )
            updated_count += 1
        else:
            print(f"  ⚠️  {party_code} ({party_name}): Could not extract color")
            error_count += 1
            # Keep old color if exists
            if old_color != "N/A":
                assigned_colors[party_code] = old_color

    # Save updated data
    print(f"\n{'=' * 60}")
    print("Summary:")
    print(f"  Updated: {updated_count} parties")
    print(f"  Merged colors: {merged_count} parties (used secondary color)")
    print(f"  Skipped: {skipped_count} parties (no icon)")
    print(f"  Errors:  {error_count} parties")
    print(f"{'=' * 60}")

    # Save to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Updated party data saved to: {OUTPUT_FILE}")
    print("\nYou can now commit this change and merge it to master.")


if __name__ == "__main__":
    main()
