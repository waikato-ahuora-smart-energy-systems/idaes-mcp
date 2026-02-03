
The main difference is lines 132 to 133:

```python
# the heater has one degree of freedom, the heat duty. Instead of specifying that, we will specify the outlet temperature and inlet temperature
m.fs.cooler.outlet.enth_mass.fix(m.fs.helmholtz_water.htpx(p=201325 * units.Pa,x=0,amount_basis=AmountBasis.MASS,with_units=True))
m.fs.heater.heat_duty.fix(50000 * units.kW)
```

The heater is putting in too much energy for it to be feasible.