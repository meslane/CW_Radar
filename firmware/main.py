import machine
import time
import struct

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
    def __init__(self, spi: machine.SPI, cs: machine.Pin):
        super().__init__(spi, cs)
    
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
        
        Returns: dict containing the GPS register contents
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
        reg_dict["PLL_NUM"] = (regs[43] << 16) | regs[42]
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
    
    def set_rf_output_mux(self, output, source):
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

def main():
    radar_spi = machine.SPI(baudrate=100000,
                polarity=0,
                phase=0,
                firstbit=machine.SPI.MSB,
                bits=8,
                id=0,
                sck=machine.Pin(18),
                mosi=machine.Pin(19),
                miso=machine.Pin(16))

    radar_csb = machine.Pin(17, machine.Pin.OUT)
    
    pll = LMX2594(radar_spi, radar_csb)
    
    #PLL Programming
    pll.reset()
    pll.enable_readback_blind() #enable SPI read
    time.sleep(0.01)
    
    print(pll.read_lock_status_regs())
    print(pll.read_mash_reset_regs())
    print(pll.read_lock_detect_regs())
    print(pll.read_sync_reg())
    print(pll.read_divider_output_regs())
    print(pll.read_vco_cal_regs())
    print(pll.read_charge_pump_reg())
    print(pll.read_input_regs())
    print(pll.read_general_regs())
    
if __name__ == "__main__":
    main()