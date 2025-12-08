import machine
import time
import struct
import sys

def modify_word(word: int, bits: tuple[int, int], data: int):
    '''
    Modify specified bits in a 16 bit word
    
    word: 16 bit word to modify
    bits: bits in the word to modify, in the range [low, high] inclusive
    data: new data to insert into the provided bits, note bits outside the range will be ignored
    
    Returns: word with selected bits modified
    '''

    for i in range(bits[0], bits[1] + 1):
        word &= 0xFFFF & ~(0x1 << i)
        word |= ((data >> (i - bits[0])) & 0x0001) << i
        
    return word

def get_bits(word: int, bits: tuple[int, int]):
    '''
    Return specificed bits in a 16 bit word shifted down to the 0 position
    
    word: 16 bit word to read
    bits: bits in the word to get, in the range [low, high] inclusive
    '''
    bitmask = 0
    for i in range(bits[0], bits[1] + 1):
        bitmask = (bitmask << 1) | 0x1

    bitmask <<= bits[0]

    return (word & bitmask) >> bits[0]

class SPI_Device:
    def __init__(self, spi: machine.SPI, cs: machine.Pin):
        self.spi = spi
        self.cs = cs
        
        self.cs.value(1) #set CS high to deselect chip by default
        
    def spi_write_byte(self, data: int):
        byte = struct.pack(">B", data)
        self.spi.write(byte)

class LMX2594(SPI_Device):
    def __init__(self, spi: machine.SPI, cs: machine.Pin, rclk: machine.Pin, f_osc_in: float):
        '''
        spi: micropython SPI interface class defining the SPI driver connected to the PLL
        cs: micropython pin class defining the pin used for the CSB signal
        f_osc_in: frequency of the PLL reference oscillator in Hz
        '''
        super().__init__(spi, cs)
        self.rclk = rclk
        self.f_osc_in = f_osc_in
    
    def read(self, addr: int):
        '''
        Read a 16 bit word from the selected device address
        
        addr: device register to read from
        
        Returns: 16 bit word from selected address
        '''
        a_byte = (addr & 0x7F) | 0x80 #first byte must be high for serial read
        
        self.cs.value(0)
        self.spi_write_byte(a_byte)
        data = self.spi.read(2) #LMX registers are 16 bits
        self.cs.value(1)
        
        return int.from_bytes(data, "big")
    
    def write(self, addr: int, data: int):
        '''
        Write a 16 bit word to the selected device address
        
        addr: device register address to write
        data: 16 bit word to write to address
        '''
        a_byte = addr & 0x7F #first byte must be low for serial write
        
        #pack 16 bit word into two bytes
        d1_byte = (data >> 8) & 0xFF
        d2_byte = data & 0xFF
        
        self.cs.value(0)
        self.spi_write_byte(a_byte)
        self.spi_write_byte(d1_byte)
        self.spi_write_byte(d2_byte)
        self.cs.value(1)
        
    def modify(self, addr: int, bits: tuple[int, int], data: int):
        '''
        Write and modify bits within the selected range
        
        addr: Address to poke
        bits: Range of bits to modify in the format [low, high] inclusive
        data: New value for the selected bits. Out of range bits will be ignored.
        '''

        reg = self.read(addr)
        new_reg = modify_word(reg, bits, data)
        
        self.write(addr, new_reg)
    
    def register_dump(self):
        '''
        Read all registers and dump their values into a dict for fruther processing
        
        Returns: a dict in the format {addr: data}
        '''
        reg_dict = {}

        for addr in range(0, 113):
            reg_dict[addr] = self.read(addr)
            
        return reg_dict
        
    def reset(self):
        '''
        Reset device to default values by asserting RESET bit in R0
        '''
        self.modify(0x00, [1,1], 1)
        
    def enable_readback_blind(self):
        '''
        Writes a predefined magic number to R0 to enable SPI readback. You should call this immediately after reset
        
        We can't use modify here because register reads will fail by default on device init
        '''
        self.write(0x00, 0b0010010000010000)
        
    def powerdown(self, power: int):
        '''
        Take device in/out of low power mode
        '''
        assert power in [0,1]
        
        self.modify(0, [0,0], power)
    
    def set_muxout(self, en: int):
        '''
        Sets the MUXOUT_SEL bit to enable/disable register readback over SPI
        WARNING: setting en = 1 will break the ability to read/modify over SPI until enable_readback_blind is called
        
        en: If 0, enable SPI read. If 1, use MUXOUT to indicate lock detect
        '''
        assert en in [0,1]
        
        self.modify(0x00, [2,2], en)
        
    def read_general_regs(self):
        '''
        Read R0, R1, and R7 for general PLL settings
        
        Returns: a dict with the fields of interest for R0, R1, and R7      
        '''
        regs = {}
        
        for addr in [0, 1, 7]:
            regs[addr] = self.read(addr)
            
        reg_dict = {}
        
        reg_dict["RAMP_EN"] = get_bits(regs[0], [15,15])
        reg_dict["VCO_PHASE_SYNC"] = get_bits(regs[0], [14,14])
        reg_dict["OUT_MUTE"] = get_bits(regs[0], [9,9])
        reg_dict["FCAL_HPFD_ADJ"] = get_bits(regs[0], [7,8])
        reg_dict["FCAL_LPFD_ADJ"] = get_bits(regs[0], [5,6])
        reg_dict["FCAL_EN"] = get_bits(regs[0], [3,3])
        reg_dict["MUXOUT_LD_SEL"] = get_bits(regs[0], [2,2])
        reg_dict["RESET"] = get_bits(regs[0], [1,1])
        reg_dict["POWERDOWN"] = get_bits(regs[0], [0,0])
        
        reg_dict["CAL_CLK_DIV"] = get_bits(regs[1], [0,2])
        
        reg_dict["OUT_FORCE"] = get_bits(regs[7], [14,14])
        
        return reg_dict
 
    def read_input_regs(self):
        '''
        Read R9 - R12 for input path settings
        
        Returns: a dict with the fields of interest for R9 - R12        
        '''
        regs = {}
        
        for addr in range(9,13):
            regs[addr] = self.read(addr)
            
        reg_dict = {}
        
        reg_dict["OSC_2X"] = get_bits(regs[9], [12,12])
        reg_dict["MULT"] = get_bits(regs[10], [7,11])
        reg_dict["PLL_R"] = get_bits(regs[11], [4,11])
        reg_dict["PLL_R_PRE"] = get_bits(regs[12], [0,11])
        
        return reg_dict

    def read_charge_pump_reg(self):
        '''
        Read R14 for charge pump current setting
        
        Returns: dict containing the CPG register contents
        '''
        r14 = self.read(14)
        
        return {"CPG": get_bits(r14, [4,6])}

    def read_vco_cal_regs(self):
        '''
        Read R4 - R20 for VCO calibration settings
        
        Returns: a dict with the fields of interest for R4 - R20
        '''
        regs = {}
        
        for addr in [4, 8, 16, 17, 19, 20]:
            regs[addr] = self.read(addr)
            
        reg_dict = {}
        
        reg_dict["ACAL_CMP_DELAY"] = get_bits(regs[4], [8,15])
        reg_dict["VCO_DACISET_FORCE"] = get_bits(regs[8], [14,14])
        reg_dict["VCO_CAPCTRL_FORCE"] = get_bits(regs[8], [11,11])
        reg_dict["VCO_DACISET"] = get_bits(regs[16], [0,8])
        reg_dict["VCO_DACISET_STRT"] = get_bits(regs[17], [0,8])
        reg_dict["VCO_CAPCTRL"] = get_bits(regs[19], [0,7])
        reg_dict["VCO_SEL"] = get_bits(regs[20], [11,13])
        reg_dict["VCO_SEL_FORCE"] = get_bits(regs[20], [10,10])
    
        return reg_dict
    
    def read_divider_output_regs(self):
        '''
        Read R34 - R46 for N Divider, MASH, and Output Register settings
        
        Returns: a dict with the fields of interest for R34 - R46
        '''
        regs = {}
        
        for addr in range(34, 47):
            if addr not in [35]:
                regs[addr] = self.read(addr)
            
        reg_dict = {}
        
        reg_dict["PLL_N"] = (get_bits(regs[34], [0,2]) << 16) | regs[36]
        reg_dict["MASH_SEED_EN"] = get_bits(regs[37], [15,15])
        reg_dict["PFD_DLY_SEL"] = get_bits(regs[37], [8,13])
        reg_dict["PLL_DEN"] = (regs[38] << 16) | regs[39]
        reg_dict["MASH_SEED"] = (regs[41] << 16) | regs[40]
        reg_dict["PLL_NUM"] = (regs[42] << 16) | regs[43]
        reg_dict["OUTA_PWR"] = get_bits(regs[44], [8,13])
        reg_dict["OUTB_PD"] = get_bits(regs[44], [7,7])
        reg_dict["OUTA_PD"] = get_bits(regs[44], [6,6])
        reg_dict["MASH_RESET_N"] = get_bits(regs[44], [5,5])
        reg_dict["MASH_ORDER"] = get_bits(regs[44], [0,2])
        reg_dict["OUTA_MUX"] = get_bits(regs[45], [11,12])
        reg_dict["OUT_ISET"] = get_bits(regs[45], [9,10])
        reg_dict["OUTB_PWR"] = get_bits(regs[45], [0,5])
        reg_dict["OUTB_MUX"] = get_bits(regs[46], [0,1])

        return reg_dict
    
    def read_sync_reg(self):
        '''
        Read the SYNC/SysRefReq config register
        
        Returns: a dict with the fields of interest for R58
        '''
        r58 = self.read(58)
        
        reg_dict = {}
        
        reg_dict["INPIN_IGNORE"] = get_bits(r58, [15,15])
        reg_dict["INPIN_HYST"] = get_bits(r58, [14,14])
        reg_dict["INPIN_LVL"] = get_bits(r58, [12,13])
        reg_dict["INPIN_FMT"] = get_bits(r58, [9,11])
        
        return reg_dict
    
    def read_lock_detect_regs(self):
        '''
        Read the lock detect config registers
        
        Returns: a dict with the fields of interest for R59, R60
        '''
        r59 = self.read(59)
        r60 = self.read(60)
        
        reg_dict = {}
        
        reg_dict["LD_TYPE"] = get_bits(r59, [0,0])
        reg_dict["LD_DLY"] = r60
        
        return reg_dict
    
    def read_mash_reset_regs(self):
        '''
        Read the mash reset count
        
        Returns: a dict with the mash reset count from R69, R70
        '''
        r69 = self.read(69)
        r70 = self.read(70)
        
        return {"MASH_RST_COUNT": (r69 << 16) | r70}
    
    def read_ramp_cal_regs(self):
        '''
        Read ramp calibration registers
        
        Returns: a dict with relevant fields for R78 - R80
        '''
        regs = {}
        
        for addr in range(78, 81):
            regs[addr] = self.read(addr)
            
        reg_dict = {}
        
        reg_dict["RAMP_THRESH"] = (get_bits(regs[78], [11,11]) << 32) | (regs[79] << 16) | regs[80]
        reg_dict["QUICK_RECAL_EN"] = get_bits(regs[78], [9,9])
        reg_dict["VCO_CAPCTRL_STRT"] = get_bits(regs[78], [1,8])
        
        return reg_dict
    
    def read_ramp_limit_regs(self):
        '''
        Read ramp limit registers
        
        Returns: a dict with relevant fields for R81 - R86
        '''
        regs = {}
        
        for addr in range(81,87):
            regs[addr] = self.read(addr)
            
        reg_dict = {}
        
        reg_dict["RAMP_LIMIT_HIGH"] = (get_bits(regs[81], [0,0]) << 32) | (regs[82] << 16) | regs[83]
        reg_dict["RAMP_LIMIT_LOW"] = (get_bits(regs[84], [0,0]) << 32) | (regs[85] << 16) | regs[86]
        
        return reg_dict
    
    def read_ramp_trigger_regs(self):
        '''
        Read ramp tripper, burst, and reset registers
        
        Returns: a dict with relevant fields for R96 and R97
        '''
        regs = {}
        
        for addr in range(96,98):
            regs[addr] = self.read(addr)
            
        reg_dict = {}
        
        reg_dict["RAMP_BURST_EN"] = get_bits(regs[96], [15,15])
        reg_dict["RAMP_BURST_COUNT"] = get_bits(regs[96], [2,14])
        
        reg_dict["RAMP0_RST"] = get_bits(regs[97], [15,15])
        reg_dict["RAMP_TRIGA"] = get_bits(regs[97], [3,6])
        reg_dict["RAMP_TRIGB"] = get_bits(regs[97], [7,10])
        reg_dict["RAMP_BURST_TRIG"] = get_bits(regs[97], [0,1])
        
        return reg_dict
    
    def read_ramp_cfg_regs(self):
        '''
        Read ramp configuration registers
        
        Returns: a dict with relevant fields for R98 - R106
        
        '''
        regs = {}
        
        for addr in range(98,107):
            regs[addr] = self.read(addr)
            
        reg_dict = {}
        
        reg_dict["RAMP0_INC"] = (get_bits(regs[98], [2,15]) << 16) | regs[99]
        reg_dict["RAMP0_DLY"] = get_bits(regs[98], [0,0])
        reg_dict["RAMP0_LEN"] =  regs[100]
        
        reg_dict["RAMP1_DLY"] = get_bits(regs[101], [6,6])
        reg_dict["RAMP1_RST"] = get_bits(regs[101], [5,5])
        
        reg_dict["RAMP0_NEXT"] = get_bits(regs[101], [4,4])
        reg_dict["RAMP0_NEXT_TRIG"] = get_bits(regs[101], [0,1])
        
        reg_dict["RAMP1_INC"] = (get_bits(regs[102], [0,13]) << 16) | regs[103]
        reg_dict["RAMP1_LEN"] =  regs[104]
        
        reg_dict["RAMP_DLY_CNT"] =  get_bits(regs[105], [6,15])
        reg_dict["RAMP_MANUAL"] =  get_bits(regs[105], [5,5])
        reg_dict["RAMP1_NEXT"] =  get_bits(regs[105], [4,4])
        reg_dict["RAMP1_NEXT_TRIG"] =  get_bits(regs[105], [0,1])
        
        reg_dict["RAMP_TRIG_CAL"] = get_bits(regs[106], [4,4])
        reg_dict["RAMP_SCALE_COUNT"] = get_bits(regs[106], [0,2])
        
        return reg_dict
    
    def read_lock_status_regs(self):
        '''
        Read the VCO lock status registers and return their data
        
        Returns: a dict with the fields of interest for R110 - R112
        '''
        r110 = self.read(110)
        r111 = self.read(111)
        r112 = self.read(112)
        
        reg_dict = {}
        
        reg_dict['LD_VTUNE'] = get_bits(r110, [9,10])
        reg_dict['VCO_SEL'] = get_bits(r110, [5,7])
        reg_dict['VCO_CAPCTRL'] = get_bits(r111, [0,7])
        reg_dict['VCO_DACISET'] = get_bits(r112, [0,8])
        
        return reg_dict
    
    def set_rf_output_mux(self, output: int, source: int):
        '''
        Set the source for the selected output
        
        output: 0 = OUTA_MUX, 1 = OUTB_MUX
        source:
            0 = channel divider
            1 = VCO (default on reset)
            2 = SysRef on OUTB only, reserved on OUTA
            3 = High Impedance/disabled
        '''
        assert 0 <= source <= 3
        
        if output == 0:
            self.modify(45, [11,12], source)
        elif output == 1:
            self.modify(46, [0,1], source)
            
    def enable_calibration(self, cal: int):
        '''
        Enable/disable VCO calibration
        
        cal:
            1 = enable calibration
            0 = disable calibration (default on reset)
        '''
        assert cal in [0,1]
        
        self.modify(0, [3,3], cal)
        
    def calc_f_pd(self):
        '''
        Calculate expected phase detector reference frequency given a known external reference freq
        
        Returns: f_pd in Hz
        '''
        f_pd = self.f_osc_in
        
        inp_regs = self.read_input_regs()
        
        f_pd *= (inp_regs['OSC_2X'] + 1)
        f_pd /= inp_regs['PLL_R_PRE']
        f_pd *= inp_regs['MULT']
        f_pd /= inp_regs['PLL_R']
        
        return f_pd
        
    def calc_f_vco(self):
        '''
        Calculate expected VCO frequency given a known reference freq
        NOTE: this value cannot be < 7.5 GHz or the PLL will not lock!!
        
        Returns: VCO frequency in Hz
        '''
        outp_regs = self.read_divider_output_regs()
        
        f_pd = self.calc_f_pd()
        f_vco = f_pd * (outp_regs['PLL_N'] + (outp_regs['PLL_NUM']/outp_regs['PLL_DEN']))
        
        return f_vco
    
    def calc_f_smclk(self):
        '''
        Calculate the system reference clock frequency given a known reference freq
        
        Returns: f_smclk frequency in Hz
        '''
        clk_div = self.read_general_regs()["CAL_CLK_DIV"]
        f_smclk = self.f_osc_in / (2 ** clk_div)
        
        return f_smclk
    
    def set_smclk_div(self, clk_div: int):
        '''
        Set the divider for the state machine clock
        
        clk_div: clock divider, div = 2^clk_div
        '''
        assert 0 <= clk_div <= 3
        self.modify(1, [0,2], clk_div)
        
    def set_vco_recal_delay(self, delay_count: int, scale_count: int):
        '''
        Set the recalibration delay/scale count for VCO recalibration in automatic ramping mode
        
        Delay = 1/f_smclk * delay_count * 2^(scale_count)
        
        delay_count: integer delay count value
        scale_count: scale count value
        
        Returns: the calculated recalibration delay in seconds
        '''
        assert 0 <= delay_count < 0x200
        assert 0 <= scale_count <= 7
        
        self.modify(105, [6,15], delay_count)
        self.modify(106, [0,2], scale_count)
        
        return 1/self.calc_f_smclk() * delay_count * (2 ** scale_count)
        
    def program_vco_dividers(self, N: int, num: int, denom: int):
        '''
        Load, N, numerator, and denominator values in order into the divier
        f_VCO = f_pd * (N + (num/denom))
        
        N: N divider integer value
        num: numerator integer value
        denom: denominator integer value
        '''
        #Should write N first per datasheet
        self.modify(34, [0,2], get_bits(N, [16,18]))
        self.write(36, (N & 0xFFFF))
        
        #Numerator
        self.write(42, (num >> 16) & 0xFFFF)
        self.write(43, num & 0xFFFF)
        
        #Denominator
        self.write(38, (denom >> 16) & 0xFFFF)
        self.write(39, denom & 0xFFFF)
        
    def set_input_doubler(self, en):
        '''
        Enable/disable the reference frequency doubler
        
        en: 1 = enable doubler, 0 = disable doubler
        '''
        assert en in [0,1]
        
        self.modify(9, [12,12], en)
        
    def set_input_multiplier(self, mult):
        '''
        Set the input multiplier for the reference input
        
        mult: input multiplication: 1 = bypass, 3-7 = mult
        '''
        assert (3 <= mult <= 7) or (mult == 1)
        
        self.modify(10, [7,11], mult)
        
    def set_output_power(self, output: int, power: int):
        '''
        Set output power for selected channel
        
        output: 0 = OUTA, 1 = OUTB
        '''
        assert output in [0,1]
        assert 0 <= power <= 31
        
        if output == 0:
            self.modify(44, [8,13], power)
        elif output == 1:
            self.modify(45, [0,5], power)
            
    def set_channel_divider(self, div_index: int):
        '''
        Set the output channel divider
        
        div_index: index of the output divider. See datasheet for more info
        '''
        assert 0 <= div_index <= 17
        
        buffer = int(div_index != 0) #1 if not using index 0 for divide / 2
        
        self.modify(31, [14,14], buffer)
        self.modify(75, [6,10], div_index)
        
    def enable_ramp(self, en: int):
        '''
        Enable/disable frequency ramping
        '''
        assert en in [0,1]
        
        self.modify(0, [15,15], en)
        
    def set_ramp_trig_type(self, ramp: int, trig: int):
        '''
        Determine what triggers the specified ramp
        
        ramp: which ramp to modify (0 or 1)
        trig: what to trigger off of
            0 = Timeout counter
            1 = Trigger A
            2 = Trigger B
        '''
        assert ramp in [0,1]
        assert 0 <= trig <= 2
        
        if ramp == 0:
            self.modify(101, [0,1], trig)
        elif ramp == 1:
            self.modify(105, [0,1], trig)
            
    def set_ramp_trig(self, trig_idx: int, trig: int):
        '''
        Set the trigger for ramp trigger A/B
        
        trig_idx: 0 = TRIGA, 1 = TRIGB
        trig:
            0 = disabled
            1 = RAMPCLK rising
            2 = RAMPDIR rising
            4 = always triggered
            9 = RAMPCLK falling
            10 = RAMPDIR falling
        '''
        assert trig_idx in [0,1]
        assert trig in [0,1,2,4,9,10]
        
        if trig_idx == 0: #A
            self.modify(97, [3,6], trig)
        elif trig_idx == 1: #B
            self.modify(97, [7,10], trig)
        
    def configure_ramp(self, span_hz: float, ramp_len_s: float, thresh_hz: float,
                       neg_ramp: bool = False, free_run: bool = True):
        '''
        Helper function to set up for an automatic triangle wave FMCW frequency sweep on RAMP0
        
        NOTE: enable_calibration latches the ramp, so FCAL_EN must == 0 when this function is called
        Setting FCAL_EN = 1 will start the ramp
        
        span_hz: total span of sweep in the freuency domain. RAMP_THRESH is set to this value * 2
                    Note that this is the span of the sweep at the VCO
                    IMPORTANT: If you have an output divider, that must be accounted for
        ramp_len_ns: length of time it takes for one ramp to complete in seconds
        thresh_hz: how long to sweep for before recalibrating the VCO
        neg_ramp: whether or not to sweep in reverse (from highest to lowest freq)
        free_run: run indefinitely if true, trigger on RCLK rising edge if false
        '''
        f_pd = self.calc_f_pd()
        f_vco = self.calc_f_vco()
        
        self.modify(105, [5,5], 0) #Configure for automatic ramping mode
        
        if free_run:
            self.set_ramp_trig_type(0,0) #Trigger next ramp on current ramp's timeout
            self.set_ramp_trig(0,0) #Disable trigger A
        else:
            self.set_ramp_trig_type(0,1) #Trigger off of trigger A
            self.set_ramp_trig(0,1) #Trigger on RampClk
        
        self.modify(101, [4,4], 0) #RAMP0 comes after RAMP0
        
        self.modify(97, [15,15], 1) #Reset ramp at start (required for automatic mode)
        self.modify(106, [4,4], 0) #No VCO recal after ramp
        self.write(60, 0) #Set LD_DLY to 0 so we get lock immediately
        self.modify(106, [0,2], 1) #Set RAMP_SCALE_COUNT to 1 for RAMP_DLY *= 2^1
        self.modify(78, [9,9], 1) #Enable quick recal for ramp
        
        #write ramp params
        ramp_len = int(ramp_len_s * f_pd) #calc number of PD cycles to feed into RAMP_LEN
        ramp_inc = int(span_hz / f_pd * 16777216 / ramp_len) #how much to increment numerator each cycle
        ramp_thresh = int((thresh_hz / f_pd) * 16777216) #how long before we recal
        
        #apply 2's complement if we want a negative ramp
        if neg_ramp:
            ramp_inc = 0x40000000 - ramp_inc
        
        print(ramp_len)
        print(ramp_inc)
        print(ramp_thresh)
        
        assert 0x0000 <= ramp_len <= 0xFFFF
        assert 0x0000 <= ramp_inc <= 0x3FFFFFFF
        assert 0x0000 <= ramp_thresh <= 0x1FFFFFFF
        
        self.modify(98, [2,15], (ramp_inc >> 16) & 0x3FFF)
        self.write(99, (ramp_inc & 0xFFFF))
        
        self.write(100, ramp_len)
        
        self.modify(78, [11,11], (ramp_thresh >> 32) & 0x0001)
        self.write(79, (ramp_thresh >> 16) & 0xFFFF)
        self.write(80, ramp_thresh & 0xFFFF)
        
        #move ramp limits far enough away to not trip them
        f_high = f_vco + (span_hz * 2)
        f_low = f_vco - (span_hz * 2)
        
        ramp_high = int((f_high - f_vco)/f_pd * 16777216)
        ramp_low = int(0x200000000 - 16777216 * (f_vco - f_low)/f_pd)
        
        #write limit registers
        self.modify(81, [0,0], (ramp_high >> 32) & 0x0001)
        self.write(82, (ramp_high >> 16) & 0xFFFF)
        self.write(83, ramp_high & 0xFFFF)
        
        self.modify(84, [0,0], (ramp_low >> 32) & 0x0001)
        self.write(85, (ramp_low >> 16) & 0xFFFF)
        self.write(86, ramp_low & 0xFFFF)

def main():
    F_REFCLK = 10e6
    
    radar_spi = machine.SPI(baudrate=5000000,
                polarity=0,
                phase=0,
                firstbit=machine.SPI.MSB,
                bits=8,
                id=0,
                sck=machine.Pin(18),
                mosi=machine.Pin(19),
                miso=machine.Pin(16))

    radar_csb = machine.Pin(17, machine.Pin.OUT)
    radar_rclk = machine.Pin(20, machine.Pin.OUT)
    
    pll = LMX2594(radar_spi, radar_csb, radar_rclk, F_REFCLK)
    
    #PLL Programming
    pll.rclk.value(0) #set RCLK low
    pll.reset()
    pll.enable_readback_blind() #enable SPI read
    time.sleep(0.01)
    
    pll.set_input_doubler(1) #Use doubler
    pll.set_input_multiplier(1) #bypass since we are using doubler
    
    pll.program_vco_dividers(580, 1, 4294967295) #Den must be this value in ramp mode
    pll.set_channel_divider(0) #index 0 = divide by 2
    
    pll.set_rf_output_mux(0, 0) #Set output A to use the channel divider, cancels out the x2 input doubler    
    pll.set_output_power(0, 9) #Set output power to meet desired LO input level (this setting produces lowest FMCW spurs)
    pll.set_smclk_div(0) #Divide by 1 for 10 MHz state machine clock
    print(pll.set_vco_recal_delay(300,0)) #set delay to 25 us
    pll.enable_calibration(0)
    
    time.sleep(0.1)
    
    bw_ramp = 50e6
    
    #Ramp descending as app note shows that there is more cal headroom when descending at >= room temp
    pll.configure_ramp(bw_ramp * 2, 2.0e-3, bw_ramp * 3, neg_ramp=True, free_run=False)
    pll.enable_ramp(1)
    pll.enable_calibration(1)
                               
    time.sleep(0.1)
    
    print(pll.read_lock_status_regs())
    print(pll.read_ramp_cfg_regs())
    print(pll.read_ramp_trigger_regs())
    print(pll.read_ramp_limit_regs())
    print(pll.read_ramp_cal_regs())
    print(pll.read_mash_reset_regs())
    print(pll.read_lock_detect_regs())
    print(pll.read_sync_reg())
    print(pll.read_divider_output_regs())
    print(pll.read_vco_cal_regs())
    print(pll.read_charge_pump_reg())
    print(pll.read_input_regs())
    print(pll.read_general_regs())
    
    print(pll.calc_f_pd())
    print(pll.calc_f_vco()) #This should be 5.75 GHz x 2
    print(pll.calc_f_smclk())
    
    while sys.stdin.read(2) != "q\n":
        pll.rclk.value(1) #trigger ramp
        print("Triggered ramp!")
        #time.sleep(0.01)
        pll.rclk.value(0) #reset pin
    
    print("Powering Down")
    pll.powerdown(1)

    
if __name__ == "__main__":
    main()