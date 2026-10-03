"""GST in integer paise, rounded half-up once on the invoice total (AUT-878).

Inclusive prices round the taxable value; exclusive prices round the GST.
Never round each seat separately. CGST takes the lower half, SGST the remainder.
"""

from dataclasses import dataclass
from typing import Literal

TaxMode = Literal["inclusive", "exclusive"]
GST_RATE_BASIS_POINTS = 1800
_BASIS = 10_000


def _half_up(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


def _validate(amount: int, mode: TaxMode) -> None:
    if type(amount) is not int or amount < 0:
        raise ValueError("tax amounts must be nonnegative integer paise")
    if mode not in {"inclusive", "exclusive"}:
        raise ValueError("unknown GST mode")


@dataclass(frozen=True, slots=True)
class TaxBreakdown:
    mode: TaxMode
    rate_basis_points: int
    taxable_minor: int
    gst_minor: int
    total_minor: int

    def components(self, *, interstate: bool) -> tuple[int, int, int]:
        """CGST, SGST, IGST; the caller resolves buyer/seller states."""
        if interstate:
            return 0, 0, self.gst_minor
        cgst = self.gst_minor // 2
        return cgst, self.gst_minor - cgst, 0


def calculate_tax(amount_minor: int, mode: TaxMode) -> TaxBreakdown:
    """Catalogue total (price times seats), before tax for exclusive prices."""
    _validate(amount_minor, mode)
    if mode == "inclusive":
        return tax_from_total(amount_minor, mode)
    gst = _half_up(amount_minor * GST_RATE_BASIS_POINTS, _BASIS)
    return TaxBreakdown(mode, GST_RATE_BASIS_POINTS, amount_minor, gst, amount_minor + gst)


def tax_from_total(total_minor: int, mode: TaxMode) -> TaxBreakdown:
    """Read the saved charged total; never consult today's catalogue price."""
    _validate(total_minor, mode)
    taxable = _half_up(total_minor * _BASIS, _BASIS + GST_RATE_BASIS_POINTS)
    return TaxBreakdown(mode, GST_RATE_BASIS_POINTS, taxable, total_minor - taxable, total_minor)
