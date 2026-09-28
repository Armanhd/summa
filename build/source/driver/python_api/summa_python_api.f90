module summa_python_api

  use, intrinsic :: iso_c_binding, only: c_int, c_double, c_char, c_null_char

  use nr_type,          only: i4b, rkind
  use summa_type,       only: config_info
  use summa_type,       only: parallel_context_type
  use summa_config,     only: read_summa_config
  use summa_simulation, only: evaluate_objective
  use globalData, only: iRunMode, iRunModeFull
  
  implicit none
  private

  public :: summa_py_init
  public :: summa_py_evaluate

  type(config_info), save :: config_saved

  type(parallel_context_type), save :: domain_parallel
  type(parallel_context_type), save :: instance_parallel

  logical, save :: initialized = .false.

contains


  ! ============================================================
  ! Initialize one SUMMA model instance from a TOML configuration.
  !
  ! Intended usage:
  !   one Python worker process -> one initialized SUMMA case
  !
  ! Configuration is read only once per worker.
  ! ============================================================

  integer(c_int) function summa_py_init( &
      config_path_c,                     &
      message_c,                         &
      message_len)                       &
      bind(C, name="summa_py_init")

    character(kind=c_char), intent(in)  :: config_path_c(*)
    character(kind=c_char), intent(out) :: message_c(*)

    integer(c_int), value :: message_len

    character(len=:), allocatable :: config_path
    character(len=1024)           :: message

    integer(i4b) :: err

    summa_py_init = 0_c_int
    message = ''

    if (initialized) then
      call copy_message_to_c( &
          'SUMMA Python API already initialized', &
          message_c, message_len)
      return
    endif

    ! Serial SUMMA execution inside this Python worker.
    !
    ! Parallelism is supplied outside SUMMA by Python/MPI/Slurm.
    domain_parallel%comm = 0
    domain_parallel%rank = 0
    domain_parallel%size = 1

    instance_parallel%comm = 0
    instance_parallel%rank = 0
    instance_parallel%size = 1

    call c_string_to_fortran(config_path_c, config_path)

    ! Python wrapper does not use SUMMA command-line parsing.
    ! Coupled mizuRoute requires a full-domain SUMMA simulation.
    config_saved%read_cli = .false.
    iRunMode = iRunModeFull

    call read_summa_config( &
        trim(config_path),  &
        config_saved,       &
        err,                &
        message)
    if (err /= 0) then
      call copy_message_to_c(trim(message), message_c, message_len)
      summa_py_init = int(err, c_int)
      return
    endif

    initialized = .true.

  end function summa_py_init


  ! ============================================================
  ! Evaluate one parameter vector.
  !
  ! Returns the objective function already configured in TOML.
  !
  ! No simulation NetCDF time series are required when
  ! simulation.write_timeseries = false.
  ! ============================================================

  integer(c_int) function summa_py_evaluate( &
      nparam,                                &
      param_names_c,                         &
      name_width,                            &
      param_values_c,                        &
      objective_c,                           &
      message_c,                             &
      message_len)                           &
      bind(C, name="summa_py_evaluate")

    integer(c_int), value :: nparam
    integer(c_int), value :: name_width
    integer(c_int), value :: message_len

    character(kind=c_char), intent(in)  :: param_names_c(*)
    character(kind=c_char), intent(out) :: message_c(*)

    real(c_double), intent(in)  :: param_values_c(*)
    real(c_double), intent(out) :: objective_c

    character(len=:), allocatable :: param_name(:)
    real(rkind), allocatable      :: param_value(:)

    character(len=1024) :: message

    integer(i4b) :: err
    integer(i4b) :: sample_id

    integer :: i
    integer :: j
    integer :: offset

    real(rkind) :: objective

    summa_py_evaluate = 0_c_int

    objective_c = 0.0_c_double
    message = ''
    sample_id = 0

    if (.not. initialized) then
      call copy_message_to_c( &
          'SUMMA Python API is not initialized', &
          message_c, message_len)

      summa_py_evaluate = 1_c_int
      return
    endif

    if (nparam <= 0) then
      call copy_message_to_c( &
          'No calibration parameters supplied', &
          message_c, message_len)

      summa_py_evaluate = 2_c_int
      return
    endif

    allocate(character(len=name_width) :: param_name(nparam))
    allocate(param_value(nparam))

    do i = 1, nparam

      param_name(i) = ''

      offset = (i - 1) * name_width

      do j = 1, name_width
        if (param_names_c(offset + j) == c_null_char) exit
        param_name(i)(j:j) = param_names_c(offset + j)
      enddo

      param_name(i) = trim(param_name(i))
      param_value(i) = real(param_values_c(i), rkind)

    enddo

    call evaluate_objective( &
        config_saved,          &
        domain_parallel,       &
        instance_parallel,     &
        sample_id,             &
        param_name,            &
        param_value,           &
        objective,             &
        err,                   &
        message)

    if (err /= 0) then
      call copy_message_to_c(trim(message), message_c, message_len)
      summa_py_evaluate = int(err, c_int)
      return
    endif

    objective_c = real(objective, c_double)

    deallocate(param_name)
    deallocate(param_value)

  end function summa_py_evaluate


  ! ============================================================
  ! C string -> allocatable Fortran string
  ! ============================================================

  subroutine c_string_to_fortran(c_string, f_string)

    character(kind=c_char), intent(in) :: c_string(*)
    character(len=:), allocatable, intent(out) :: f_string

    integer :: i
    integer :: n

    n = 0

    do i = 1, 4096
      if (c_string(i) == c_null_char) exit
      n = n + 1
    enddo

    allocate(character(len=n) :: f_string)

    do i = 1, n
      f_string(i:i) = c_string(i)
    enddo

  end subroutine c_string_to_fortran


  ! ============================================================
  ! Fortran message -> C string
  ! ============================================================

  subroutine copy_message_to_c(message, message_c, message_len)

    character(*), intent(in) :: message

    character(kind=c_char), intent(out) :: message_c(*)

    integer(c_int), value :: message_len

    integer :: i
    integer :: n

    do i = 1, message_len
      message_c(i) = c_null_char
    enddo

    n = min(len_trim(message), int(message_len) - 1)

    do i = 1, n
      message_c(i) = message(i:i)
    enddo

  end subroutine copy_message_to_c


end module summa_python_api