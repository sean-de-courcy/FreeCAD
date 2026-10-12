// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2010 Jürgen Riegel <juergen.riegel@web.de>              *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include <algorithm>
#include <cmath>
#include <limits>

#include <fmt/format.h>

#include <Base/QuantityPy.h>
#include <Base/UnitPy.h>

#include "PropertyUnits.h"
#include "Expression.h"


using namespace App;
using namespace Base;
using namespace std;


const PropertyQuantityConstraint::Constraints LengthStandard = {
    0.0, std::numeric_limits<double>::max(), 1.0};
const PropertyQuantityConstraint::Constraints AngleStandard = {-360, 360, 1.0};

namespace
{
// "Length (mm)", or "mm^-1" for a unit without a name.
std::string describeUnit(const Base::Unit& unit)
{
    std::string type = unit.getTypeString();
    return type.empty() ? unit.getString() : fmt::format("{} ({})", type, unit.getString());
}

const char* nameOf(const Property& prop)
{
    const char* name = prop.getName();
    return name ? name : "the property";
}
}  // namespace

//**************************************************************************
// PropertyQuantity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyQuantity, App::PropertyFloat)

Base::Quantity PropertyQuantity::getQuantityValue() const
{
    Quantity quantity(_dValue, _Unit);
    quantity.setFormat(_Format);
    return quantity;
}

const char* PropertyQuantity::getEditorName() const
{
    return "Gui::PropertyEditor::PropertyUnitItem";
}

PyObject* PropertyQuantity::getPyObject()
{
    return new QuantityPy(new Quantity(_dValue, _Unit));
}

Base::Quantity PropertyQuantity::createQuantityFromPy(PyObject* value)
{
    Base::Quantity quant;

    if (PyUnicode_Check(value)) {
        quant = Quantity::parse(PyUnicode_AsUTF8(value));
    }
    else if (PyFloat_Check(value)) {
        quant = Quantity(PyFloat_AsDouble(value), _Unit);
    }
    else if (PyLong_Check(value)) {
        quant = Quantity(double(PyLong_AsLong(value)), _Unit);
    }
    else if (PyObject_TypeCheck(value, &(QuantityPy::Type))) {
        Base::QuantityPy* pcObject = static_cast<Base::QuantityPy*>(value);
        quant = *(pcObject->getQuantityPtr());
    }
    else {
        std::string error = std::string("wrong type as quantity: ");
        error += value->ob_type->tp_name;
        throw Base::TypeError(error);
    }

    return quant;
}

void PropertyQuantity::setPyObject(PyObject* value)
{
    // Set the unit if Unit object supplied, else check the unit
    // and set the value

    if (PyObject_TypeCheck(value, &(UnitPy::Type))) {
        Base::UnitPy* pcObject = static_cast<Base::UnitPy*>(value);
        Base::Unit unit = *(pcObject->getUnitPtr());
        aboutToSetValue();
        _Unit = unit;
        _unitAdopted = false;
        hasSetValue();
    }
    else {
        Base::Quantity quant = createQuantityFromPy(value);

        if (quant.isDimensionless()) {
            PropertyFloat::setValue(quant.getValue());
            return;
        }

        if (_Unit != quant.getUnit()) {
            throw Base::UnitsMismatchError("Not matching Unit!");
        }

        PropertyFloat::setValue(quant.getValue());
    }
}

// FreeCAD-CH (ops#319): an expression result took over the property's unit unchecked, so a
// Length set to `30 deg` built a 30 mm box. A unit set by the property's class (or by setUnit)
// is now checked; a property without one (a plain PropertyQuantity) still takes the result's.
// A result without a unit takes the property's, as before.
void PropertyQuantity::checkPathUnit(const Base::Quantity& q) const
{
    if (q.isDimensionless() || q.getUnit() == _Unit || _unitAdopted || _Unit == Base::Unit::One) {
        return;
    }
    throw Base::UnitsMismatchError(fmt::format(
        "Unit mismatch: {} needs {}, but the value {} has {}",
        nameOf(*this),
        describeUnit(_Unit),
        q.getUserString(),
        describeUnit(q.getUnit())
    ));
}

void PropertyQuantity::setPathValue(const ObjectIdentifier& /*path*/, const boost::any& value)
{
    auto q = App::anyToQuantity(value);
    checkPathUnit(q);
    aboutToSetValue();
    if (!q.isDimensionless() && q.getUnit() != _Unit) {
        _Unit = q.getUnit();
        _unitAdopted = true;
    }
    _dValue = q.getValue();
    setValue(q.getValue());
}

const boost::any PropertyQuantity::getPathValue(const ObjectIdentifier& /*path*/) const
{
    Quantity quantity(_dValue, _Unit);
    quantity.setFormat(_Format);
    return quantity;
}

//**************************************************************************
// PropertyQuantityConstraint
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyQuantityConstraint, App::PropertyQuantity)


void PropertyQuantityConstraint::setConstraints(const Constraints* sConstrain)
{
    _ConstStruct = sConstrain;
}

const char* PropertyQuantityConstraint::getEditorName() const
{
    return "Gui::PropertyEditor::PropertyUnitConstraintItem";
}

const PropertyQuantityConstraint::Constraints* PropertyQuantityConstraint::getConstraints() const
{
    return _ConstStruct;
}

double PropertyQuantityConstraint::getMinimum() const
{
    if (_ConstStruct) {
        return _ConstStruct->LowerBound;
    }
    return std::numeric_limits<double>::min();
}

double PropertyQuantityConstraint::getMaximum() const
{
    if (_ConstStruct) {
        return _ConstStruct->UpperBound;
    }
    return std::numeric_limits<double>::max();
}

double PropertyQuantityConstraint::getStepSize() const
{
    if (_ConstStruct) {
        return _ConstStruct->StepSize;
    }
    return 1.0;
}

// FreeCAD-CH (ops#319): a value outside the constraints was clamped silently (`Length = -5` stored
// 0 mm). It is refused now, from Python and from expressions alike. Within rounding of a bound
// (`2*pi rad` on an angle limited to 360 deg) the value counts as the bound.
double PropertyQuantityConstraint::checkedValue(double value) const
{
    if (!_ConstStruct) {
        return value;
    }
    const double lower = _ConstStruct->LowerBound;
    const double upper = _ConstStruct->UpperBound;
    auto tolerance = [](double bound) {
        return 1e-9 * std::max(1.0, std::abs(bound));
    };
    auto shown = [this](double v) {
        return Base::Quantity(v, _Unit).getUserString();
    };
    if (value < lower) {
        if (value >= lower - tolerance(lower)) {
            return lower;
        }
        throw Base::ValueError(fmt::format(
            "{}: {} is below the minimum, {}", nameOf(*this), shown(value), shown(lower)
        ));
    }
    if (value > upper) {
        if (value <= upper + tolerance(upper)) {
            return upper;
        }
        throw Base::ValueError(fmt::format(
            "{}: {} is above the maximum, {}", nameOf(*this), shown(value), shown(upper)
        ));
    }
    return value;
}

void PropertyQuantityConstraint::setPyObject(PyObject* value)
{
    Base::Quantity quant = createQuantityFromPy(value);

    if (!quant.isDimensionless() && _Unit != quant.getUnit()) {
        throw Base::UnitsMismatchError("Not matching Unit!");
    }

    PropertyFloat::setValue(checkedValue(quant.getValue()));  // clazy:exclude=skipped-base-method
}

void PropertyQuantityConstraint::setPathValue(const ObjectIdentifier& path, const boost::any& value)
{
    auto q = App::anyToQuantity(value);
    checkPathUnit(q);
    q.setValue(checkedValue(q.getValue()));
    PropertyQuantity::setPathValue(path, q);
}

// ------------------------------------------------------
// now all properties
// ------------------------------------------------------

//**************************************************************************
// PropertyAcceleration
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyAcceleration, App::PropertyQuantity)

PropertyAcceleration::PropertyAcceleration()
{
    setUnit(Base::Unit::Acceleration);
}

//**************************************************************************
// PropertyAmountOfSubstance
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyAmountOfSubstance, App::PropertyQuantity)

PropertyAmountOfSubstance::PropertyAmountOfSubstance()
{
    setUnit(Base::Unit::AmountOfSubstance);
}

//**************************************************************************
// PropertyAngle
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyAngle, App::PropertyQuantityConstraint)

PropertyAngle::PropertyAngle()
{
    setUnit(Base::Unit::Angle);
    setConstraints(&AngleStandard);
}

//**************************************************************************
// PropertyArea
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyArea, App::PropertyQuantityConstraint)

PropertyArea::PropertyArea()
{
    setUnit(Base::Unit::Area);
    setConstraints(&LengthStandard);
}

//**************************************************************************
// PropertyCompressiveStrength
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyCompressiveStrength, App::PropertyQuantity)

PropertyCompressiveStrength::PropertyCompressiveStrength()
{
    setUnit(Base::Unit::CompressiveStrength);
}

//**************************************************************************
// PropertyCurrentDensity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyCurrentDensity, App::PropertyQuantity)

PropertyCurrentDensity::PropertyCurrentDensity()
{
    setUnit(Base::Unit::CurrentDensity);
}

//**************************************************************************
// PropertyDensity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyDensity, App::PropertyQuantity)

PropertyDensity::PropertyDensity()
{
    setUnit(Base::Unit::Density);
}

//**************************************************************************
// PropertyDissipationRate
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyDissipationRate, App::PropertyQuantity)

PropertyDissipationRate::PropertyDissipationRate()
{
    setUnit(Base::Unit::DissipationRate);
}

//**************************************************************************
// PropertyDistance
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyDistance, App::PropertyQuantity)

PropertyDistance::PropertyDistance()
{
    setUnit(Base::Unit::Length);
}

//**************************************************************************
// PropertyDynamicViscosity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyDynamicViscosity, App::PropertyQuantity)

PropertyDynamicViscosity::PropertyDynamicViscosity()
{
    setUnit(Base::Unit::DynamicViscosity);
}

//**************************************************************************
// PropertyElectricalCapacitance
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyElectricalCapacitance, App::PropertyQuantity)

PropertyElectricalCapacitance::PropertyElectricalCapacitance()
{
    setUnit(Base::Unit::ElectricalCapacitance);
}

//**************************************************************************
// PropertyElectricalInductance
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyElectricalInductance, App::PropertyQuantity)

PropertyElectricalInductance::PropertyElectricalInductance()
{
    setUnit(Base::Unit::ElectricalInductance);
}

//**************************************************************************
// PropertyElectricalConductance
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyElectricalConductance, App::PropertyQuantity)

PropertyElectricalConductance::PropertyElectricalConductance()
{
    setUnit(Base::Unit::ElectricalConductance);
}

//**************************************************************************
// PropertyElectricalConductivity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyElectricalConductivity, App::PropertyQuantity)

PropertyElectricalConductivity::PropertyElectricalConductivity()
{
    setUnit(Base::Unit::ElectricalConductivity);
}

//**************************************************************************
// PropertyElectricalResistance
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyElectricalResistance, App::PropertyQuantity)

PropertyElectricalResistance::PropertyElectricalResistance()
{
    setUnit(Base::Unit::ElectricalResistance);
}

//**************************************************************************
// PropertyElectricCharge
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyElectricCharge, App::PropertyQuantity)

PropertyElectricCharge::PropertyElectricCharge()
{
    setUnit(Base::Unit::ElectricCharge);
}

//**************************************************************************
// PropertySurfaceChargeDensity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertySurfaceChargeDensity, App::PropertyQuantity)

PropertySurfaceChargeDensity::PropertySurfaceChargeDensity()
{
    setUnit(Base::Unit::SurfaceChargeDensity);
}

//**************************************************************************
// PropertyVolumeChargeDensity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyVolumeChargeDensity, App::PropertyQuantity)

PropertyVolumeChargeDensity::PropertyVolumeChargeDensity()
{
    setUnit(Base::Unit::VolumeChargeDensity);
}

//**************************************************************************
// PropertyElectricCurrent
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyElectricCurrent, App::PropertyQuantity)

PropertyElectricCurrent::PropertyElectricCurrent()
{
    setUnit(Base::Unit::ElectricCurrent);
}

//**************************************************************************
// PropertyElectricPotential
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyElectricPotential, App::PropertyQuantity)

PropertyElectricPotential::PropertyElectricPotential()
{
    setUnit(Base::Unit::ElectricPotential);
}

//**************************************************************************
// PropertyFrequency
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyFrequency, App::PropertyQuantity)

PropertyFrequency::PropertyFrequency()
{
    setUnit(Base::Unit::Frequency);
}

//**************************************************************************
// PropertyForce
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyForce, App::PropertyQuantity)

PropertyForce::PropertyForce()
{
    setUnit(Base::Unit::Force);
}

//**************************************************************************
// PropertyHeatFlux
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyHeatFlux, App::PropertyQuantity)

PropertyHeatFlux::PropertyHeatFlux()
{
    setUnit(Base::Unit::HeatFlux);
}

//**************************************************************************
// PropertyInverseArea
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyInverseArea, App::PropertyQuantity)

PropertyInverseArea::PropertyInverseArea()
{
    setUnit(Base::Unit::InverseArea);
}

//**************************************************************************
// PropertyInverseLength
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyInverseLength, App::PropertyQuantity)

PropertyInverseLength::PropertyInverseLength()
{
    setUnit(Base::Unit::InverseLength);
}

//**************************************************************************
// PropertyInverseVolume
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyInverseVolume, App::PropertyQuantity)

PropertyInverseVolume::PropertyInverseVolume()
{
    setUnit(Base::Unit::InverseVolume);
}

//**************************************************************************
// PropertyKinematicViscosity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyKinematicViscosity, App::PropertyQuantity)

PropertyKinematicViscosity::PropertyKinematicViscosity()
{
    setUnit(Base::Unit::KinematicViscosity);
}

//**************************************************************************
// PropertyLength
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyLength, App::PropertyQuantityConstraint)

PropertyLength::PropertyLength()
{
    setUnit(Base::Unit::Length);
    enableNegative(false);
}

void PropertyLength::enableNegative(bool on)
{
    setConstraints(on ? nullptr : &LengthStandard);
}

//**************************************************************************
// PropertyLuminousIntensity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyLuminousIntensity, App::PropertyQuantity)

PropertyLuminousIntensity::PropertyLuminousIntensity()
{
    setUnit(Base::Unit::LuminousIntensity);
}

//**************************************************************************
// PropertyMagneticFieldStrength
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyMagneticFieldStrength, App::PropertyQuantity)

PropertyMagneticFieldStrength::PropertyMagneticFieldStrength()
{
    setUnit(Base::Unit::MagneticFieldStrength);
}

//**************************************************************************
// PropertyMagneticFlux
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyMagneticFlux, App::PropertyQuantity)

PropertyMagneticFlux::PropertyMagneticFlux()
{
    setUnit(Base::Unit::MagneticFlux);
}

//**************************************************************************
// PropertyMagneticFluxDensity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyMagneticFluxDensity, App::PropertyQuantity)

PropertyMagneticFluxDensity::PropertyMagneticFluxDensity()
{
    setUnit(Base::Unit::MagneticFluxDensity);
}

//**************************************************************************
// PropertyMagnetization
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyMagnetization, App::PropertyQuantity)

PropertyMagnetization::PropertyMagnetization()
{
    setUnit(Base::Unit::Magnetization);
}

//**************************************************************************
// PropertyElectromagneticPotential
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyElectromagneticPotential, App::PropertyQuantity)

PropertyElectromagneticPotential::PropertyElectromagneticPotential()
{
    setUnit(Base::Unit::ElectromagneticPotential);
}

//**************************************************************************
// PropertyMass
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyMass, App::PropertyQuantity)

PropertyMass::PropertyMass()
{
    setUnit(Base::Unit::Mass);
}

//**************************************************************************
// PropertyMoment
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyMoment, App::PropertyQuantity)

PropertyMoment::PropertyMoment()
{
    setUnit(Base::Unit::Moment);
}

//**************************************************************************
// PropertyPressure
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyPressure, App::PropertyQuantity)

PropertyPressure::PropertyPressure()
{
    setUnit(Base::Unit::Pressure);
}

//**************************************************************************
// PropertyPower
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyPower, App::PropertyQuantity)

PropertyPower::PropertyPower()
{
    setUnit(Base::Unit::Power);
}

//**************************************************************************
// PropertySpecificEnergy
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertySpecificEnergy, App::PropertyQuantity)

PropertySpecificEnergy::PropertySpecificEnergy()
{
    setUnit(Base::Unit::SpecificEnergy);
}

//**************************************************************************
// PropertySpecificHeat
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertySpecificHeat, App::PropertyQuantity)

PropertySpecificHeat::PropertySpecificHeat()
{
    setUnit(Base::Unit::SpecificHeat);
}

//**************************************************************************
// PropertySpeed
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertySpeed, App::PropertyQuantity)

PropertySpeed::PropertySpeed()
{
    setUnit(Base::Unit::Velocity);
}

//**************************************************************************
// PropertyStiffness
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyStiffness, App::PropertyQuantity)

PropertyStiffness::PropertyStiffness()
{
    setUnit(Base::Unit::Stiffness);
}

//**************************************************************************
// PropertyStiffnessDensity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyStiffnessDensity, App::PropertyQuantity)

PropertyStiffnessDensity::PropertyStiffnessDensity()
{
    setUnit(Base::Unit::StiffnessDensity);
}

//**************************************************************************
// PropertyTemperature
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyTemperature, App::PropertyQuantity)

PropertyTemperature::PropertyTemperature()
{
    setUnit(Base::Unit::Temperature);
}

//**************************************************************************
// PropertyThermalConductivity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyThermalConductivity, App::PropertyQuantity)

PropertyThermalConductivity::PropertyThermalConductivity()
{
    setUnit(Base::Unit::ThermalConductivity);
}

//**************************************************************************
// PropertyThermalExpansionCoefficient
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyThermalExpansionCoefficient, App::PropertyQuantity)

PropertyThermalExpansionCoefficient::PropertyThermalExpansionCoefficient()
{
    setUnit(Base::Unit::ThermalExpansionCoefficient);
}


//**************************************************************************
// PropertyThermalTransferCoefficient
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyThermalTransferCoefficient, App::PropertyQuantity)

PropertyThermalTransferCoefficient::PropertyThermalTransferCoefficient()
{
    setUnit(Base::Unit::ThermalTransferCoefficient);
}

//**************************************************************************
// PropertyTime
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyTime, App::PropertyQuantity)

PropertyTime::PropertyTime()
{
    setUnit(Base::Unit::TimeSpan);
}

//**************************************************************************
// PropertyShearModulus
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyShearModulus, App::PropertyQuantity)

PropertyShearModulus::PropertyShearModulus()
{
    setUnit(Base::Unit::ShearModulus);
}

//**************************************************************************
// PropertyStress
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyStress, App::PropertyQuantity)

PropertyStress::PropertyStress()
{
    setUnit(Base::Unit::Stress);
}

//**************************************************************************
// PropertyUltimateTensileStrength
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyUltimateTensileStrength, App::PropertyQuantity)

PropertyUltimateTensileStrength::PropertyUltimateTensileStrength()
{
    setUnit(Base::Unit::UltimateTensileStrength);
}

//**************************************************************************
// PropertyVacuumPermittivity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyVacuumPermittivity, App::PropertyQuantity)

PropertyVacuumPermittivity::PropertyVacuumPermittivity()
{
    setUnit(Base::Unit::VacuumPermittivity);
}

//**************************************************************************
// PropertyVelocity
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyVelocity, App::PropertyQuantity)

PropertyVelocity::PropertyVelocity()
{
    setUnit(Base::Unit::Velocity);
}

//**************************************************************************
// PropertyVolume
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyVolume, App::PropertyQuantityConstraint)

PropertyVolume::PropertyVolume()
{
    setUnit(Base::Unit::Volume);
    setConstraints(&LengthStandard);
}

//**************************************************************************
// PropertyVolumeFlowRate
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyVolumeFlowRate, App::PropertyQuantity)

PropertyVolumeFlowRate::PropertyVolumeFlowRate()
{
    setUnit(Base::Unit::VolumeFlowRate);
}

//**************************************************************************
// PropertyVolumetricThermalExpansionCoefficient
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyVolumetricThermalExpansionCoefficient, App::PropertyQuantity)

PropertyVolumetricThermalExpansionCoefficient::PropertyVolumetricThermalExpansionCoefficient()
{
    setUnit(Base::Unit::VolumetricThermalExpansionCoefficient);
}

//**************************************************************************
// PropertyWork
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyWork, App::PropertyQuantity)

PropertyWork::PropertyWork()
{
    setUnit(Base::Unit::Work);
}

//**************************************************************************
// PropertyYieldStrength
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyYieldStrength, App::PropertyQuantity)

PropertyYieldStrength::PropertyYieldStrength()
{
    setUnit(Base::Unit::YieldStrength);
}

//**************************************************************************
// PropertyYoungsModulus
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyYoungsModulus, App::PropertyQuantity)

PropertyYoungsModulus::PropertyYoungsModulus()
{
    setUnit(Base::Unit::YoungsModulus);
}

