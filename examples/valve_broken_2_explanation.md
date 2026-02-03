
In the broken one, the temperature of the water coming in is very hot. However, we have set the outlet temperature to be 88 deg C. The water goes through the valve, which reduces the temperature by reducing pressure. However, it reduces the pressure so low it's basically a vaccuum, and it doesn't reduce the temperature very much. so it fails to solve.

In the working one, the temperature of the water coming in is cooler - 99 degrees C means it will still be liquid water. This means that when it goes through the valve, it can phase change to gas, getting cooler in the process (absorbing the energy as a phase change instead.) 

So you could fix the broken flowsheet by:
- increasing the pressure of the inlet (until the water is a liquid at 120 deg C, then it has a phase change to help it get cooler)
- increasing the temperature of the outlet (so that it's at a temperature high enough that reducing the pressure can get the temperature low enough) (this may not work much)
- Switching the fixed  variable from outlet temperature to outlet pressure (much easier problem to solve)
- decreasing the temperature of the inlet (so it's cool enough to reach the temperature we set and goes through a phase change from liq-> gas) (*this is what we did in the working example*)